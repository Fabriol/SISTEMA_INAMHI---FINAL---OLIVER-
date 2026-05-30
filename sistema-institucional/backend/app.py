from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from mysql.connector import pooling
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import jwt
import datetime
import os
import re
import json
import traceback

app = Flask(__name__)
app.config["SECRET_KEY"] = "clave_super_secreta_inamhi_2026_segura"

CORS(
    app,
    resources={r"/api/*": {"origins": "http://localhost:4200"}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"]
)

@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "http://localhost:4200")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
    return response
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf"}

ROLES_VALIDOS = [
    "Administrador",
    "Talento Humano - Recepcion Documentos",
    "Ex Funcionario",
    "Administrativa",
    "Financiera",
    "TICs",
    "Seguridad"
]

ESTADOS_VALIDOS = ["ACTIVO", "INHABILITADO"]

ESTADOS_DOCUMENTO = [
    "BORRADOR",
    "PENDIENTE",
    "APROBADO",
    "RECHAZADO",
    "FINALIZADO"
]

db_pool = pooling.MySQLConnectionPool(
    pool_name="inamhi_pool",
    pool_size=10,
    pool_reset_session=True,
    host="localhost",
    user="root",
    password="root",
    database="sistema_institucional",
    port=3306
)

def get_connection():
    return db_pool.get_connection()

def _ensure_mediumtext():
    """Ensure respuesta column can hold base64 firma images (run once at startup)."""
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'sistema_institucional'
              AND TABLE_NAME   = 'formulario_respuestas'
              AND COLUMN_NAME  = 'respuesta'
        """)
        row = cursor.fetchone()
        if row and row[0].lower() not in ('mediumtext', 'longtext'):
            cursor.execute(
                "ALTER TABLE formulario_respuestas MODIFY COLUMN respuesta MEDIUMTEXT"
            )
            conn.commit()
    except Exception as e:
        print(f"[startup] _ensure_mediumtext: {e}")
    finally:
        close_db(cursor, conn)

try:
    _ensure_mediumtext()
except Exception:
    pass

def close_db(cursor=None, conn=None):
    try:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    except Exception as e:
        print("Error cerrando conexión:", e)

def limpiar_texto(texto):
    return re.sub(r"\s+", " ", (texto or "").strip())

def solo_letras(texto):
    return bool(re.match(r"^[a-zA-ZÁÉÍÓÚáéíóúÑñ\s]+$", texto or ""))

def normalizar_usuario(texto):
    texto = (texto or "").strip().lower()
    reemplazos = {
        "á": "a", "é": "e", "í": "i",
        "ó": "o", "ú": "u", "ñ": "n"
    }

    for a, b in reemplazos.items():
        texto = texto.replace(a, b)

    return re.sub(r"[^a-z0-9._-]", "", texto)

def generar_usuario(nombres, apellidos):
    nombres = normalizar_usuario(nombres)
    apellidos = normalizar_usuario(apellidos).replace(" ", "")
    return nombres[0] + apellidos if nombres and apellidos else ""

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def obtener_usuario_token():
    token = request.headers.get("Authorization", "")

    if token:
        token = token.replace("Bearer ", "").strip()

    if not token:
        token = request.args.get("token", "").strip()

    if not token:
        return None

    try:
        data = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        return {
            "id": data["id"],
            "usuario": data["usuario"],
            "rol": data["rol"]
        }
    except Exception as e:
        print("ERROR TOKEN:", e)
        return None

def validar_login():
    user_token = obtener_usuario_token()

    if not user_token:
        return None, (jsonify({"mensaje": "No autorizado"}), 401)

    return user_token, None

def validar_admin():
    user_token, error = validar_login()

    if error:
        return None, error

    if user_token["rol"] != "Administrador":
        return None, (jsonify({"mensaje": "Solo el Administrador puede acceder"}), 403)

    return user_token, None

def registrar_auditoria(usuario, rol, modulo, accion, detalle):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO auditoria (usuario, rol, modulo, accion, detalle)
            VALUES (%s, %s, %s, %s, %s)
        """, (usuario, rol, modulo, accion, detalle))

        conn.commit()

    except Exception as e:
        print("Error auditoría:", e)

    finally:
        close_db(cursor, conn)

@app.route("/api/test", methods=["GET"])
def test():
    return jsonify({"estado": "ok", "mensaje": "Backend funcionando"}), 200

@app.route("/api/auth/login", methods=["POST"])
def login():
    conn = None
    cursor = None

    try:
        data = request.get_json(silent=True) or {}

        usuario = normalizar_usuario(data.get("usuario"))
        password = data.get("password")

        if not usuario or not password:
            return jsonify({"mensaje": "Usuario y contraseña son obligatorios"}), 400

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, nombres, apellidos, usuario, rol, estado
            FROM usuarios
            WHERE usuario = %s AND password = %s
            LIMIT 1
        """, (usuario, password))

        user = cursor.fetchone()

        if not user:
            return jsonify({"mensaje": "Usuario o contraseña incorrectos"}), 401

        if user["estado"] != "ACTIVO":
            return jsonify({"mensaje": "Usuario inhabilitado"}), 403

        token = jwt.encode({
            "id": user["id"],
            "usuario": user["usuario"],
            "rol": user["rol"],
            "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=8)
        }, app.config["SECRET_KEY"], algorithm="HS256")

        return jsonify({
            "mensaje": "Login correcto",
            "token": token,
            "usuario": user
        }), 200

    except Exception as e:
        return jsonify({"mensaje": "Error login", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

@app.route("/api/roles", methods=["GET"])
def listar_roles():
    user_token, error = validar_admin()
    if error:
        return error

    return jsonify([{"nombre": r} for r in ROLES_VALIDOS]), 200

@app.route("/api/usuarios", methods=["GET"])
def listar_usuarios():
    conn = None
    cursor = None

    try:
        user_token, error = validar_admin()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, nombres, apellidos, usuario, rol, estado, creado_en
            FROM usuarios
            ORDER BY id DESC
        """)

        return jsonify(cursor.fetchall()), 200

    except Exception as e:
        return jsonify({"mensaje": "Error al listar usuarios", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

@app.route("/api/usuarios", methods=["POST"])
def crear_usuario():
    conn = None
    cursor = None

    try:
        user_token, error = validar_admin()
        if error:
            return error

        data = request.get_json(silent=True) or {}

        nombres = limpiar_texto(data.get("nombres"))
        apellidos = limpiar_texto(data.get("apellidos"))
        usuario = normalizar_usuario(data.get("usuario"))
        password = data.get("password")
        rol = data.get("rol")

        if not nombres or not apellidos or not password or not rol:
            return jsonify({"mensaje": "Campos obligatorios"}), 400

        if not solo_letras(nombres):
            return jsonify({"mensaje": "Nombres solo permite letras"}), 400

        if not solo_letras(apellidos):
            return jsonify({"mensaje": "Apellidos solo permite letras"}), 400

        if len(password) < 4:
            return jsonify({"mensaje": "La contraseña debe tener mínimo 4 caracteres"}), 400

        if rol not in ROLES_VALIDOS:
            return jsonify({"mensaje": "Rol inválido"}), 400

        if not usuario:
            usuario = generar_usuario(nombres, apellidos)

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM usuarios WHERE usuario = %s LIMIT 1", (usuario,))
        if cursor.fetchone():
            return jsonify({"mensaje": "Usuario ya existe"}), 400

        cursor.execute("""
            INSERT INTO usuarios (nombres, apellidos, usuario, password, rol, estado)
            VALUES (%s, %s, %s, %s, %s, 'ACTIVO')
        """, (nombres, apellidos, usuario, password, rol))

        conn.commit()

        registrar_auditoria(
            user_token["usuario"],
            user_token["rol"],
            "Usuarios",
            "Crear usuario",
            f"Se creó el usuario {usuario} con rol {rol}"
        )

        return jsonify({"mensaje": "Usuario creado"}), 201

    except Exception as e:
        return jsonify({"mensaje": "Error al crear usuario", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

@app.route("/api/usuarios/<int:id>", methods=["PUT"])
def actualizar_usuario(id):
    conn = None
    cursor = None

    try:
        user_token, error = validar_admin()
        if error:
            return error

        data = request.get_json(silent=True) or {}

        nombres = limpiar_texto(data.get("nombres"))
        apellidos = limpiar_texto(data.get("apellidos"))
        usuario = normalizar_usuario(data.get("usuario"))
        password = data.get("password")
        rol = data.get("rol")
        estado = data.get("estado", "ACTIVO")

        if not nombres or not apellidos or not usuario or not rol:
            return jsonify({"mensaje": "Campos obligatorios"}), 400

        if not solo_letras(nombres):
            return jsonify({"mensaje": "Nombres solo permite letras"}), 400

        if not solo_letras(apellidos):
            return jsonify({"mensaje": "Apellidos solo permite letras"}), 400

        if rol not in ROLES_VALIDOS:
            return jsonify({"mensaje": "Rol inválido"}), 400

        if estado not in ESTADOS_VALIDOS:
            return jsonify({"mensaje": "Estado inválido"}), 400

        if password and len(password) < 4:
            return jsonify({"mensaje": "La contraseña debe tener mínimo 4 caracteres"}), 400

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id FROM usuarios
            WHERE usuario = %s AND id != %s
            LIMIT 1
        """, (usuario, id))

        if cursor.fetchone():
            return jsonify({"mensaje": "Ese usuario ya existe"}), 400

        if password:
            cursor.execute("""
                UPDATE usuarios
                SET nombres=%s, apellidos=%s, usuario=%s, password=%s, rol=%s, estado=%s
                WHERE id=%s
            """, (nombres, apellidos, usuario, password, rol, estado, id))
        else:
            cursor.execute("""
                UPDATE usuarios
                SET nombres=%s, apellidos=%s, usuario=%s, rol=%s, estado=%s
                WHERE id=%s
            """, (nombres, apellidos, usuario, rol, estado, id))

        conn.commit()

        registrar_auditoria(
            user_token["usuario"],
            user_token["rol"],
            "Usuarios",
            "Actualizar usuario",
            f"Se actualizó el usuario ID {id}"
        )

        return jsonify({"mensaje": "Usuario actualizado"}), 200

    except Exception as e:
        return jsonify({"mensaje": "Error al actualizar usuario", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

@app.route("/api/usuarios/<int:id>/estado", methods=["PUT"])
def cambiar_estado_usuario(id):
    conn = None
    cursor = None

    try:
        user_token, error = validar_admin()
        if error:
            return error

        data = request.get_json(silent=True) or {}
        estado = data.get("estado")

        if estado not in ESTADOS_VALIDOS:
            return jsonify({"mensaje": "Estado inválido"}), 400

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE usuarios
            SET estado = %s
            WHERE id = %s
        """, (estado, id))

        conn.commit()

        registrar_auditoria(
            user_token["usuario"],
            user_token["rol"],
            "Usuarios",
            "Cambiar estado",
            f"Usuario ID {id} cambiado a {estado}"
        )

        return jsonify({"mensaje": f"Usuario cambiado a {estado}"}), 200

    except Exception as e:
        return jsonify({"mensaje": "Error al cambiar estado", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

@app.route("/api/usuarios/<int:id>", methods=["DELETE"])
def eliminar_usuario(id):
    conn = None
    cursor = None

    try:
        user_token, error = validar_admin()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM usuarios WHERE id = %s", (id,))
        conn.commit()

        registrar_auditoria(
            user_token["usuario"],
            user_token["rol"],
            "Usuarios",
            "Eliminar usuario",
            f"Se eliminó el usuario ID {id}"
        )

        return jsonify({"mensaje": "Usuario eliminado"}), 200

    except Exception as e:
        return jsonify({"mensaje": "Error al eliminar usuario", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

@app.route("/api/documentos/ver/<path:nombre>", methods=["GET"])
def ver_archivo(nombre):

    token = request.args.get("token", "").strip()

    if not token:
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()

    if not token:
        return jsonify({"mensaje": "No autorizado"}), 401

    try:
        data = jwt.decode(
            token,
            app.config["SECRET_KEY"],
            algorithms=["HS256"]
        )

    except jwt.ExpiredSignatureError:
        return jsonify({"mensaje": "Token expirado. Inicie sesión nuevamente."}), 401

    except Exception as e:
        print("ERROR TOKEN VER PDF:", str(e))
        return jsonify({"mensaje": "Token inválido", "error": str(e)}), 401

    ruta = os.path.join(UPLOAD_FOLDER, nombre)

    if not os.path.exists(ruta):
        return jsonify({"mensaje": "Archivo no encontrado"}), 404

    return send_from_directory(
        UPLOAD_FOLDER,
        nombre,
        mimetype="application/pdf"
    )

@app.route("/api/documentos/descargar/<path:nombre>", methods=["GET"])
def descargar_archivo(nombre):
    user_token, error = validar_login()
    if error:
        return error

    return send_from_directory(
        UPLOAD_FOLDER,
        nombre,
        as_attachment=True
    )

@app.route("/api/documentos", methods=["GET"])
def listar_documentos():
    conn = None
    cursor = None

    try:
        user_token, error = validar_login()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, titulo, descripcion, estado, creado_por, creado_por_nombre, archivo, creado_en
            FROM documentos
            ORDER BY id DESC
        """)

        return jsonify(cursor.fetchall()), 200

    except Exception as e:
        return jsonify({"mensaje": "Error al listar documentos", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

@app.route("/api/documentos", methods=["POST"])
def crear_documento():
    conn = None
    cursor = None

    try:
        user_token, error = validar_login()
        if error:
            return error

        titulo = limpiar_texto(request.form.get("titulo"))
        descripcion = limpiar_texto(request.form.get("descripcion"))
        estado = request.form.get("estado", "BORRADOR")

        if estado not in ESTADOS_DOCUMENTO:
            return jsonify({"mensaje": "Estado inválido"}), 400

        if not titulo or not descripcion:
            return jsonify({"mensaje": "Título y descripción son obligatorios"}), 400

        archivo = request.files.get("archivo")
        nombre_archivo = None

        if archivo and archivo.filename:
            if not allowed_file(archivo.filename):
                return jsonify({"mensaje": "Solo se permiten archivos PDF"}), 400

            nombre_limpio = secure_filename(archivo.filename)
            fecha = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            nombre_archivo = f"{fecha}_{nombre_limpio}"
            archivo.save(os.path.join(UPLOAD_FOLDER, nombre_archivo))

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO documentos (titulo, descripcion, estado, creado_por, creado_por_nombre, archivo)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            titulo,
            descripcion,
            estado,
            user_token["id"],
            user_token["usuario"],
            nombre_archivo
        ))

        conn.commit()

        registrar_auditoria(
            user_token["usuario"],
            user_token["rol"],
            "Documentos",
            "Crear documento",
            f"Se creó el documento {titulo}"
        )

        return jsonify({"mensaje": "Documento creado correctamente"}), 201

    except Exception as e:
        return jsonify({"mensaje": "Error al crear documento", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

def puede_modificar_documento(user_token, documento_id):
    if user_token["rol"] == "Administrador":
        return True

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT creado_por
            FROM documentos
            WHERE id = %s
            LIMIT 1
        """, (documento_id,))

        documento = cursor.fetchone()

        if not documento:
            return False

        return str(documento["creado_por"]) == str(user_token["id"])

    finally:
        close_db(cursor, conn)

@app.route("/api/documentos/<int:id>", methods=["PUT"])
def actualizar_documento(id):
    conn = None
    cursor = None

    try:
        user_token, error = validar_login()
        if error:
            return error

        if not puede_modificar_documento(user_token, id):
            return jsonify({"mensaje": "No tiene permisos para editar este documento"}), 403

        data = request.get_json(silent=True) or {}

        titulo = limpiar_texto(data.get("titulo"))
        descripcion = limpiar_texto(data.get("descripcion"))
        estado = data.get("estado")

        if estado not in ESTADOS_DOCUMENTO:
            return jsonify({"mensaje": "Estado inválido"}), 400

        if not titulo or not descripcion or not estado:
            return jsonify({"mensaje": "Campos obligatorios"}), 400

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE documentos
            SET titulo=%s, descripcion=%s, estado=%s
            WHERE id=%s
        """, (titulo, descripcion, estado, id))

        conn.commit()

        registrar_auditoria(
            user_token["usuario"],
            user_token["rol"],
            "Documentos",
            "Actualizar documento",
            f"Se actualizó el documento ID {id}"
        )

        return jsonify({"mensaje": "Documento actualizado"}), 200

    except Exception as e:
        return jsonify({"mensaje": "Error al actualizar documento", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

@app.route("/api/documentos/<int:id>", methods=["DELETE"])
def eliminar_documento(id):
    conn = None
    cursor = None

    try:
        user_token, error = validar_login()
        if error:
            return error

        if not puede_modificar_documento(user_token, id):
            return jsonify({"mensaje": "No tiene permisos para eliminar este documento"}), 403

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT archivo FROM documentos WHERE id = %s", (id,))
        documento = cursor.fetchone()

        if not documento:
            return jsonify({"mensaje": "Documento no encontrado"}), 404

        archivo = documento.get("archivo")

        cursor.execute("DELETE FROM documentos WHERE id = %s", (id,))
        conn.commit()

        if archivo:
            ruta_archivo = os.path.join(UPLOAD_FOLDER, archivo)
            if os.path.exists(ruta_archivo):
                os.remove(ruta_archivo)

        registrar_auditoria(
            user_token["usuario"],
            user_token["rol"],
            "Documentos",
            "Eliminar documento",
            f"Se eliminó el documento ID {id}"
        )

        return jsonify({"mensaje": "Documento eliminado"}), 200

    except Exception as e:
        return jsonify({"mensaje": "Error al eliminar documento", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

@app.route("/api/reportes/resumen", methods=["GET"])
def reporte():
    conn = None
    cursor = None

    try:
        user_token, error = validar_login()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                (SELECT COUNT(*) FROM usuarios) AS usuarios,
                (SELECT COUNT(*) FROM documentos) AS documentos
        """)

        data = cursor.fetchone()

        return jsonify({
            "usuarios": data["usuarios"],
            "documentos": data["documentos"]
        }), 200

    except Exception as e:
        return jsonify({"mensaje": "Error reporte", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

@app.route("/api/reportes/estado-documentos", methods=["GET"])
def reporte_estado_documentos():
    conn = None
    cursor = None

    try:
        user_token, error = validar_admin()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT estado, COUNT(*) cantidad
            FROM documentos
            GROUP BY estado
        """)

        return jsonify(cursor.fetchall()), 200

    except Exception as e:
        return jsonify({"mensaje": "Error reporte documentos", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

@app.route("/api/auditoria", methods=["GET"])
def listar_auditoria():
    conn = None
    cursor = None

    try:
        user_token, error = validar_admin()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT *
            FROM auditoria
            ORDER BY id DESC
            LIMIT 300
        """)

        return jsonify(cursor.fetchall()), 200

    except Exception as e:
        return jsonify({"mensaje": "Error al listar auditoría", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)

# =========================
# FORMULARIOS DINÁMICOS
# =========================

@app.route("/api/formularios/usuarios-disponibles", methods=["GET"])
def usuarios_disponibles_formularios():
    conn = None
    cursor = None
    try:
        user, error = validar_admin()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, nombres, apellidos, usuario, rol, estado
            FROM usuarios
            WHERE estado = 'ACTIVO'
            ORDER BY nombres ASC, apellidos ASC
        """)

        return jsonify(cursor.fetchall()), 200

    except Exception as e:
        return jsonify({
            "mensaje": "Error al listar usuarios disponibles",
            "error": str(e)
        }), 500

    finally:
        close_db(cursor, conn)


@app.route("/api/formularios", methods=["GET"])
def listar_formularios():
    conn = None
    cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        if user["rol"] == "Administrador":
            cursor.execute("""
                SELECT *
                FROM formularios
                ORDER BY id DESC
            """)
        else:
            cursor.execute("""
                SELECT DISTINCT f.*
                FROM formularios f
                INNER JOIN formulario_asignaciones a ON f.id = a.formulario_id
                WHERE a.asignado_usuario_id = %s OR a.asignado_rol = %s
                ORDER BY f.id DESC
            """, (user["id"], user["rol"]))

        rows = cursor.fetchall()
        for r in rows:
            if r.get('porcentaje') is None:
                r['porcentaje'] = 0
        return jsonify(rows), 200
    except Exception as e:
        return jsonify({"mensaje": "Error al listar formularios", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)


@app.route("/api/formularios", methods=["POST"])
def crear_formulario():
    conn = None
    cursor = None
    try:
        user, error = validar_admin()
        if error:
            return error

        data = request.get_json(silent=True) or {}
        titulo = limpiar_texto(data.get("titulo"))
        descripcion = limpiar_texto(data.get("descripcion"))

        if not titulo or len(titulo) < 3:
            return jsonify({"mensaje": "Título obligatorio mínimo 3 caracteres"}), 400

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO formularios
            (titulo, descripcion, estado, porcentaje, creado_por, creado_por_nombre)
            VALUES (%s, %s, 'BORRADOR', 0, %s, %s)
        """, (titulo, descripcion, user["id"], user["usuario"]))

        formulario_id = cursor.lastrowid
        conn.commit()

        registrar_auditoria(
            user["usuario"],
            user["rol"],
            "Formularios",
            "Crear formulario",
            f"Se creó el formulario {titulo}"
        )

        return jsonify({
            "mensaje": "Formulario creado correctamente",
            "id": formulario_id
        }), 201

    except Exception as e:
        return jsonify({"mensaje": "Error al crear formulario", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)

@app.route("/api/formularios/<int:id>", methods=["DELETE"])
def eliminar_formulario(id):
    conn = None
    cursor = None

    try:
        user, error = validar_admin()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id FROM formularios WHERE id=%s", (id,))
        formulario = cursor.fetchone()

        if not formulario:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        cursor.execute("""
            DELETE r FROM formulario_respuestas r
            INNER JOIN formulario_preguntas p ON r.pregunta_id = p.id
            WHERE p.formulario_id = %s
        """, (id,))

        cursor.execute("DELETE FROM formulario_asignaciones WHERE formulario_id=%s", (id,))
        cursor.execute("DELETE FROM formulario_preguntas WHERE formulario_id=%s", (id,))
        cursor.execute("DELETE FROM formularios WHERE id=%s", (id,))

        conn.commit()

        return jsonify({"mensaje": "Formulario eliminado correctamente"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"mensaje": "Error al eliminar formulario", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)


@app.route("/api/formularios/<int:id>/aprobar", methods=["PATCH"])
def aprobar_formulario(id):
    conn = None
    cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id, estado, porcentaje FROM formularios WHERE id = %s", (id,))
        formulario = cursor.fetchone()

        if not formulario:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        if formulario["porcentaje"] < 100:
            return jsonify({"mensaje": "El formulario no está completo al 100%"}), 400

        cursor.execute(
            "UPDATE formularios SET estado = 'APROBADO' WHERE id = %s",
            (id,)
        )
        conn.commit()

        registrar_auditoria(
            user["usuario"], user["rol"], "Formularios",
            "Aprobación",
            f"Aprobó el formulario {id}"
        )

        return jsonify({"mensaje": "Formulario aprobado correctamente.", "estado": "APROBADO"}), 200

    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({"mensaje": "Error al aprobar formulario", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)


@app.route("/api/formularios/<int:id>", methods=["GET"])
def ver_formulario(id):
    conn = None
    cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM formularios WHERE id=%s", (id,))
        formulario = cursor.fetchone()

        if not formulario:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        if user["rol"] == "Administrador":
            cursor.execute("""
                SELECT
                    p.*,
                    a.id AS asignacion_id,
                    a.asignado_usuario_id,
                    a.asignado_rol,
                    a.estado AS estado_asignacion,
                    u.nombres AS asignado_nombres,
                    u.apellidos AS asignado_apellidos,
                    r.respuesta,
                    CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END AS ya_asignado
                FROM formulario_preguntas p
                LEFT JOIN formulario_asignaciones a ON p.id = a.pregunta_id
                LEFT JOIN usuarios u ON a.asignado_usuario_id = u.id
                LEFT JOIN formulario_respuestas r ON p.id = r.pregunta_id
                WHERE p.formulario_id = %s
                ORDER BY p.orden ASC, p.id ASC
            """, (id,))
        else:
            cursor.execute("""
                SELECT
                    p.*,
                    a.id AS asignacion_id,
                    a.asignado_usuario_id,
                    a.estado AS estado_asignacion,
                    r.respuesta
                FROM formulario_preguntas p
                INNER JOIN formulario_asignaciones a ON p.id = a.pregunta_id
                LEFT JOIN formulario_respuestas r ON p.id = r.pregunta_id
                WHERE p.formulario_id = %s
                AND a.asignado_usuario_id = %s
                ORDER BY p.orden ASC, p.id ASC
            """, (id, user["id"]))

        return jsonify({
            "formulario": formulario,
            "preguntas": cursor.fetchall()
        }), 200

    except Exception as e:
        return jsonify({"mensaje": "Error al ver formulario", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)


@app.route("/api/formularios/<int:formulario_id>/preguntas", methods=["POST"])
def agregar_pregunta(formulario_id):
    conn = None
    cursor = None
    try:
        user, error = validar_admin()
        if error:
            return error

        data = request.get_json(silent=True) or {}

        pregunta = limpiar_texto(data.get("pregunta"))
        tipo = data.get("tipo", "TEXTO")
        opciones = data.get("opciones")
        orden = data.get("orden", 0)

        tipos_validos = ["TEXTO", "NUMERO", "FECHA", "SELECT", "TEXTAREA", "CHECKBOX"]

        if not pregunta or len(pregunta) < 3:
            return jsonify({"mensaje": "Pregunta obligatoria mínimo 3 caracteres"}), 400

        if tipo not in tipos_validos:
            return jsonify({"mensaje": "Tipo de pregunta inválido"}), 400

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO formulario_preguntas
            (formulario_id, pregunta, tipo, opciones, orden)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            formulario_id,
            pregunta,
            tipo,
            json.dumps(opciones) if opciones else None,
            orden
        ))

        cursor.execute("""
            UPDATE formularios
            SET estado='BORRADOR'
            WHERE id=%s
        """, (formulario_id,))

        conn.commit()

        return jsonify({"mensaje": "Pregunta agregada correctamente"}), 201

    except Exception as e:
        return jsonify({"mensaje": "Error al agregar pregunta", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)


@app.route("/api/formularios/asignar", methods=["POST"])
def asignar_pregunta():
    conn = None
    cursor = None

    try:
        user, error = validar_admin()
        if error:
            return error

        data = request.get_json(silent=True) or {}

        formulario_id = data.get("formulario_id")
        campos = data.get("campos", [])
        usuario_id = data.get("usuario_id")

        if not formulario_id:
            return jsonify({"mensaje": "Formulario obligatorio"}), 400

        if not isinstance(campos, list) or len(campos) == 0:
            return jsonify({"mensaje": "Debe seleccionar al menos un campo"}), 400

        if not usuario_id:
            return jsonify({"mensaje": "Debe seleccionar un usuario destino"}), 400

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id
            FROM formularios
            WHERE id = %s
            LIMIT 1
        """, (formulario_id,))
        formulario = cursor.fetchone()

        if not formulario:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        cursor.execute("""
            SELECT id, nombres, apellidos, usuario, rol, estado
            FROM usuarios
            WHERE id = %s AND estado = 'ACTIVO'
            LIMIT 1
        """, (usuario_id,))
        usuario_destino = cursor.fetchone()

        if not usuario_destino:
            return jsonify({"mensaje": "Usuario destino no encontrado o inactivo"}), 404

        nuevas = 0
        bloqueadas = []
        ignoradas = []

        for campo in campos:
            if isinstance(campo, str):
                codigo = limpiar_texto(campo)
                pregunta = limpiar_texto(campo)
                tipo = "TEXTO"
                seccion = "GENERAL"
            else:
                codigo = limpiar_texto(
                    campo.get("codigo") or
                    campo.get("id") or
                    campo.get("nombre")
                )

                pregunta = limpiar_texto(
                    campo.get("pregunta") or
                    campo.get("etiqueta") or
                    codigo
                )

                tipo = limpiar_texto(campo.get("tipo") or "TEXTO")
                seccion = limpiar_texto(campo.get("seccion") or "GENERAL")

            if not codigo or not pregunta:
                ignoradas.append(campo)
                continue

            cursor.execute("""
                SELECT id
                FROM formulario_preguntas
                WHERE formulario_id = %s AND codigo = %s
                LIMIT 1
            """, (formulario_id, codigo))
            pregunta_db = cursor.fetchone()

            if pregunta_db:
                pregunta_id = pregunta_db["id"]
            else:
                cursor.execute("""
                    INSERT INTO formulario_preguntas
                    (formulario_id, codigo, pregunta, tipo, seccion, opciones, obligatorio, orden)
                    VALUES (%s, %s, %s, %s, %s, NULL, 0, 0)
                """, (
                    formulario_id,
                    codigo,
                    pregunta,
                    tipo,
                    seccion
                ))

                pregunta_id = cursor.lastrowid

            cursor.execute("""
                SELECT 
                    a.id,
                    u.nombres,
                    u.apellidos,
                    u.usuario
                FROM formulario_asignaciones a
                LEFT JOIN usuarios u ON a.asignado_usuario_id = u.id
                WHERE a.formulario_id = %s
                AND a.pregunta_id = %s
                LIMIT 1
            """, (formulario_id, pregunta_id))
            ya_asignada = cursor.fetchone()

            if ya_asignada:
                nombre = f"{ya_asignada.get('nombres') or ''} {ya_asignada.get('apellidos') or ''}".strip()

                if not nombre:
                    nombre = ya_asignada.get("usuario") or "otro usuario"

                bloqueadas.append(f"{pregunta} → ya asignada a {nombre}")
                continue

            cursor.execute("""
                INSERT INTO formulario_asignaciones
                (formulario_id, pregunta_id, asignado_usuario_id, asignado_rol, estado)
                VALUES (%s, %s, %s, NULL, 'ENVIADO')
            """, (
                formulario_id,
                pregunta_id,
                usuario_id
            ))

            nuevas += 1

        if nuevas == 0:
            conn.rollback()

            return jsonify({
                "mensaje": "No se asignó ningún campo. Las preguntas seleccionadas ya están designadas.",
                "nuevas": nuevas,
                "bloqueadas": bloqueadas,
                "ignoradas": ignoradas
            }), 400

        cursor.execute("""
            UPDATE formularios
            SET estado = 'ENVIADO'
            WHERE id = %s
        """, (formulario_id,))

        try:
            cursor.execute("""
                INSERT INTO notificaciones
                (usuario_id, rol_destino, titulo, mensaje, leido)
                VALUES (%s, NULL, %s, %s, 0)
            """, (
                usuario_id,
                "Formulario pendiente",
                f"Tiene {nuevas} campo(s) nuevo(s) por llenar."
            ))
        except Exception as notif_error:
            print("ERROR NOTIFICACION:", str(notif_error))

        conn.commit()

        registrar_auditoria(
            user["usuario"],
            user["rol"],
            "Formularios",
            "Asignar campos",
            f"Se asignaron {nuevas} campo(s) al usuario ID {usuario_id}"
        )

        return jsonify({
            "mensaje": f"{nuevas} campo(s) asignado(s) correctamente.",
            "nuevas": nuevas,
            "bloqueadas": bloqueadas,
            "ignoradas": ignoradas
        }), 201

    except Exception as e:
        if conn:
            conn.rollback()

        import traceback
        detalle = traceback.format_exc()

        print("ERROR REAL /api/formularios/asignar:")
        print(detalle)

        return jsonify({
            "mensaje": "Error al asignar campos",
            "error": str(e),
            "detalle": detalle
        }), 500

    finally:
        close_db(cursor, conn)


@app.route("/api/notificaciones", methods=["GET"])
def listar_notificaciones():
    conn = None
    cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT *
            FROM notificaciones
            WHERE (usuario_id = %s OR rol_destino = %s)
            ORDER BY id DESC
            LIMIT 50
        """, (user["id"], user["rol"]))

        return jsonify(cursor.fetchall()), 200

    except Exception as e:
        return jsonify({"mensaje": "Error al listar notificaciones", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)


@app.route("/api/notificaciones/<int:id>/leer", methods=["PUT"])
def marcar_notificacion_leida(id):
    conn = None
    cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE notificaciones
            SET leido = 1
            WHERE id=%s
            AND (usuario_id=%s OR rol_destino=%s)
        """, (id, user["id"], user["rol"]))

        conn.commit()

        return jsonify({"mensaje": "Notificación marcada como leída"}), 200

    except Exception as e:
        return jsonify({"mensaje": "Error al actualizar notificación", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)


@app.route("/api/formularios/responder", methods=["POST"])
def responder_formulario():
    conn = None
    cursor = None

    try:
        user, error = validar_login()
        if error:
            return error

        data = request.get_json(silent=True) or {}

        formulario_id = data.get("formulario_id")
        campo = limpiar_texto(data.get("campo"))
        respuesta_raw = data.get("respuesta")
        # Skip limpiar_texto for base64 firma data (starts with "data:")
        if isinstance(respuesta_raw, str) and respuesta_raw.startswith("data:"):
            respuesta = respuesta_raw
        else:
            respuesta = limpiar_texto(respuesta_raw)

        if not formulario_id or not campo or respuesta == "":
            return jsonify({"mensaje": "Datos incompletos"}), 400

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id
            FROM formulario_preguntas
            WHERE formulario_id = %s AND codigo = %s
            LIMIT 1
        """, (formulario_id, campo))

        pregunta = cursor.fetchone()

        if not pregunta:
            return jsonify({"mensaje": "Campo no encontrado en el formulario"}), 404

        pregunta_id = pregunta["id"]

        cursor.execute("""
            SELECT id, estado
            FROM formulario_asignaciones
            WHERE formulario_id = %s
            AND pregunta_id = %s
            AND asignado_usuario_id = %s
            LIMIT 1
        """, (formulario_id, pregunta_id, user["id"]))

        asignacion = cursor.fetchone()

        if user["rol"] != "Administrador" and not asignacion:
            return jsonify({"mensaje": "Este campo no fue asignado a usted"}), 403

        asignacion_id = asignacion["id"] if asignacion else None

        cursor.execute("""
            SELECT id
            FROM formulario_respuestas
            WHERE formulario_id = %s
            AND pregunta_id = %s
            LIMIT 1
        """, (formulario_id, pregunta_id))

        ya_respondido = cursor.fetchone()

        if ya_respondido:
            return jsonify({
                "mensaje": "Este campo ya fue llenado y no se puede editar."
            }), 400

        cursor.execute("""
            INSERT INTO formulario_respuestas
            (formulario_id, pregunta_id, asignacion_id, respondido_por, respuesta)
            VALUES (%s, %s, %s, %s, %s)
        """, (formulario_id, pregunta_id, asignacion_id, user["id"], respuesta))

        if asignacion_id:
            cursor.execute("""
                UPDATE formulario_asignaciones
                SET estado = 'CULMINADO',
                    fecha_culminado = NOW()
                WHERE id = %s
            """, (asignacion_id,))

        cursor.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN estado = 'CULMINADO' THEN 1 ELSE 0 END) AS completados
            FROM formulario_asignaciones
            WHERE formulario_id = %s
        """, (formulario_id,))

        progreso = cursor.fetchone()
        total = progreso["total"] or 0
        completados = progreso["completados"] or 0
        porcentaje = round((completados / total) * 100) if total > 0 else 0
        estado = "COMPLETADO" if total > 0 and porcentaje == 100 else "EN_PROCESO"

        cursor.execute("""
            UPDATE formularios
            SET porcentaje = %s,
                estado = %s
            WHERE id = %s
        """, (porcentaje, estado, formulario_id))

        conn.commit()

        return jsonify({
            "mensaje": "Campo guardado correctamente",
            "porcentaje": porcentaje,
            "estado": estado
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()
        print("[ERROR /responder]", traceback.format_exc())
        return jsonify({"mensaje": "Error al guardar campo", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)


# ═══════════════════════════════════════════════════════════════
#  CONSTANTES DE MAQUETADO DEL PDF PAZ Y SALVO
# ═══════════════════════════════════════════════════════════════

# A4 = 595.28 × 841.89 pts. Origen (0,0) = esquina inferior-izquierda.
_ML   = 40      # margen izquierdo
_MR   = 555     # margen derecho  (595 - 40)
_MT   = 800     # Y inicial del contenido (desde arriba hacia abajo)
_MB   = 55      # Y mínima antes de salto de página

# Anchos de las 3 columnas de la tabla de firmas (suma = 515 pts)
_CW   = [210, 145, 160]            # Ítem | Nombre Responsable | FirmaEC
_CX   = [_ML, _ML+210, _ML+355]   # X de inicio de cada columna: 40 | 250 | 395

_RH   = 80   # Altura UNIFORME de cada fila FirmaEC (80 pts ≈ 2.8 cm)
_HH   = 18   # Altura cabecera de sección
_CH   = 14   # Altura cabecera de columnas
_FH   = 15   # Altura fila de datos personales

# Colores (R, G, B  en 0-1)
_C_HEAD  = (0.07, 0.17, 0.37)   # azul oscuro — cabecera sección
_C_COLS  = (0.18, 0.34, 0.61)   # azul medio — cabecera columnas
_C_OK    = (0.08, 0.45, 0.08)   # verde — celda firmada
_C_PEND  = (0.50, 0.50, 0.50)   # gris  — pendiente
_C_GRAY  = (0.96, 0.96, 0.96)   # gris claro — fondo cabeceras
_C_WHITE = (1.0,  1.0,  1.0 )
_C_BLACK = (0.0,  0.0,  0.0 )

# Estructura completa: 7 secciones → 31 celdas FirmaEC
# Cada fila: (texto_ítem, campo_nombre, campo_firma)
_FIRMAEC_SECTIONS = [
    {
        "titulo": "1. TRÁMITES Y UNIDAD",
        "rows": [
            ("Informe fin de gestión / QUIPUX bandeja en cero",
             "tramites_nombre_resp1", "tramites_r1"),
            ("Fe de presentación / Claves de acceso asignadas",
             "tramites_nombre_resp2", "tramites_r2"),
            ("Entrega archivo físico y digital (LOSEP) / Acta entrega claves",
             "tramites_nombre_resp3", "tramites_r3"),
            ("Firma del Jefe Inmediato",
             "tramites_jefe_inmediato", "tramites_jefe"),
        ],
    },
    {
        "titulo": "2. GESTIÓN ADMINISTRATIVA",
        "rows": [
            ("Entrega de Informe de Actividades",
             "admin_nombre_resp1", "admin_r1"),
            ("Entrega Bienes Institucionales / Acta de Entrega-Recepción",
             "admin_nombre_resp2", "admin_r2"),
            ("Deducibles / Pasajes aéreos por justificar",
             "admin_nombre_resp3", "admin_r3"),
            ("Verificación Valor Bienes / Responsable Administrativo",
             "admin_nombre_resp4", "admin_r4"),
            ("Director/a Administrativo/a Financiero/a",
             "admin_responsable", "admin_dir"),
        ],
    },
    {
        "titulo": "3. GESTIÓN TIC",
        "rows": [
            ("Verificación Equipo / IP Fija / Liberación de accesos",
             "tic_nombre_resp1", "tic_r1"),
            ("Backup de información / Ruta de backup",
             "tic_nombre_resp2", "tic_r2"),
            ("Cierre correo institucional / eSigef / SPRYN / eSByE",
             "tic_nombre_resp3", "tic_r3"),
            ("QUIPUX / Tarjeta de Cuentas",
             "tic_nombre_resp4", "tic_r4"),
            ("Responsable TIC",
             "tic_responsable", "tic_r5"),
        ],
    },
    {
        "titulo": "4. GESTIÓN FINANCIERA",
        "rows": [
            ("Saldos contables (viáticos, caja chica, pasajes)",
             "fin_nombre_resp1", "fin_r1"),
            ("Anticipo de remuneraciones / Fondos a rendir",
             "fin_nombre_resp2", "fin_r2"),
            ("Recuperación / Devolución de valores",
             "fin_nombre_resp3", "fin_r3"),
            ("Verificación contable / Responsable Financiero",
             "fin_nombre_resp4", "fin_r4"),
            ("Director/a Administrativo/a Financiero/a",
             "fin_director", "fin_dir"),
        ],
    },
    {
        "titulo": "5. SEGURIDAD DE LA INFORMACIÓN",
        "rows": [
            ("Archivos digitales / Verificación información digital (AM 166 EGSI)",
             "seg_nombre_resp1", "seg_r1"),
            ("Archivos físicos / Entrega copia de seguridad",
             "seg_nombre_resp2", "seg_r2"),
            ("Oficial de Seguridad Institucional",
             "seg_oficial", "seg_oficial"),
        ],
    },
    {
        "titulo": "6. RECURSOS HUMANOS",
        "rows": [
            ("Capacitación — devengó cursos recibidos",
             "rrhh_resp_capacitacion", "rrhh_r1"),
            ("Evaluación del Desempeño aplicada",
             "rrhh_resp_evaluacion", "rrhh_r2"),
            ("Viajes al exterior / Informe de cumplimiento",
             "rrhh_resp_viajes", "rrhh_r3"),
            ("SIITH — actualización de datos",
             "rrhh_resp_siith", "rrhh_r4"),
            ("Vacaciones no gozadas — certificado",
             "rrhh_resp_vacaciones", "rrhh_r5"),
            ("Declaración juramentada de bienes",
             "rrhh_resp_juramentada", "rrhh_r6"),
            ("Credencial institucional / Porta credencial",
             "rrhh_resp_credencial2", "rrhh_r7"),
            ("Acta entrega-recepción bienes / Informe CD / Ropa de trabajo",
             "rrhh_resp_acta", "rrhh_r8"),
            ("Director/a de Administración de RRHH",
             "rrhh_director", "rrhh_dir"),
        ],
    },
    {
        "titulo": "7. RECEPCIÓN DE DOCUMENTOS",
        "rows": [
            ("Servidor/a que recibe el Paz y Salvo — RRHH",
             "recepcion_servidor", "recepcion_r1"),
        ],
    },
]


def _split_text(text: str, max_chars: int) -> list:
    """Divide texto en líneas que no superen max_chars, respetando palabras."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        candidate = (cur + " " + w).strip()
        if len(candidate) <= max_chars:
            cur = candidate
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _draw_page_header(c, formulario: dict, page_num: int) -> None:
    """Encabezado institucional en cada página."""
    W = 595.28
    c.setFillColorRGB(*_C_HEAD)
    c.rect(_ML, 808, W - 2 * _ML, 22, fill=1, stroke=0)
    c.setFillColorRGB(*_C_WHITE)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(W / 2, 814, "INAMHI — FORMULARIO PAZ Y SALVO")
    c.setFillColorRGB(*_C_BLACK)
    c.setFont("Helvetica", 7)
    titulo_corto = (formulario.get("titulo") or "")[:70]
    c.drawString(_ML, 804, titulo_corto)
    c.drawRightString(W - _ML, 804, f"Pág. {page_num + 1}")
    # línea separadora
    c.setStrokeColorRGB(*_C_HEAD)
    c.setLineWidth(0.5)
    c.line(_ML, 802, W - _ML, 802)
    c.setStrokeColorRGB(*_C_BLACK)
    c.setLineWidth(0.5)


def _draw_section_header(c, titulo: str, y: float) -> None:
    """Cabecera azul que ocupa todo el ancho de la tabla."""
    c.setFillColorRGB(*_C_HEAD)
    c.rect(_ML, y - _HH, _MR - _ML, _HH, fill=1, stroke=0)
    c.setFillColorRGB(*_C_WHITE)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(_ML + 4, y - _HH + 5, titulo)
    c.setFillColorRGB(*_C_BLACK)


def _draw_col_labels(c, y: float) -> None:
    """Fila de cabeceras de columnas."""
    labels = ["ÍTEM", "NOMBRE RESPONSABLE", "FIRMA RESPONSABLE (FirmaEC)"]
    c.setFillColorRGB(*_C_COLS)
    for i in range(3):
        c.rect(_CX[i], y - _CH, _CW[i], _CH, fill=1, stroke=1)
    c.setFillColorRGB(*_C_WHITE)
    c.setFont("Helvetica-Bold", 7)
    offsets = [4, 4, 4]
    for i, lbl in enumerate(labels):
        c.drawString(_CX[i] + offsets[i], y - _CH + 4, lbl)
    c.setFillColorRGB(*_C_BLACK)


def _draw_firma_row(c, y: float, item: str, nombre: str, firma_val: str,
                    campo_firma: str, sig_coords: dict, page_num: int) -> None:
    """
    Dibuja una fila de firma con altura uniforme _RH.
    Registra las coordenadas de la celda FirmaEC en sig_coords.
    """
    y_top = y
    y_bot = y - _RH

    c.setLineWidth(0.4)

    # ── Col 0: Ítem ─────────────────────────────────────────────
    c.setFillColorRGB(*_C_WHITE)
    c.rect(_CX[0], y_bot, _CW[0], _RH, fill=1, stroke=1)
    c.setFillColorRGB(*_C_BLACK)
    c.setFont("Helvetica", 7.5)
    lines = _split_text(item, 36)
    ty = y_top - 11
    for ln in lines[:5]:
        c.drawString(_CX[0] + 4, ty, ln)
        ty -= 10

    # ── Col 1: Nombre Responsable ────────────────────────────────
    c.setFillColorRGB(*_C_WHITE)
    c.rect(_CX[1], y_bot, _CW[1], _RH, fill=1, stroke=1)
    c.setFillColorRGB(*_C_BLACK)
    c.setFont("Helvetica", 7)
    if nombre and not nombre.startswith("data:") and not nombre.startswith("FIRMADO_EC:"):
        nlines = _split_text(nombre, 24)
        ny = y_top - 11
        for nl in nlines[:5]:
            c.drawString(_CX[1] + 4, ny, nl)
            ny -= 10

    # ── Col 2: FirmaEC (80 pts = uniforme) ──────────────────────
    c.setFillColorRGB(*_C_WHITE)
    c.rect(_CX[2], y_bot, _CW[2], _RH, fill=1, stroke=1)

    if firma_val and firma_val.startswith("FIRMADO_EC:"):
        parts = firma_val.split(":")
        firmante = parts[1] if len(parts) > 1 else "Firmado"
        fecha_f  = parts[2][:10] if len(parts) > 2 else ""
        # Fondo verde muy tenue
        c.setFillColorRGB(0.90, 0.97, 0.90)
        c.rect(_CX[2] + 1, y_bot + 1, _CW[2] - 2, _RH - 2, fill=1, stroke=0)
        c.setFillColorRGB(*_C_OK)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(_CX[2] + 5, y_top - 13, "FIRMADO ELECTRÓNICAMENTE")
        c.setFont("Helvetica", 6.5)
        c.setFillColorRGB(*_C_BLACK)
        flines = _split_text(firmante, 26)
        fy = y_top - 26
        for fl in flines[:4]:
            c.drawString(_CX[2] + 5, fy, fl)
            fy -= 9
        c.setFont("Helvetica", 6)
        c.setFillColorRGB(*_C_PEND)
        c.drawString(_CX[2] + 5, y_bot + 6, fecha_f)
    else:
        # Zona reservada para pyHanko — líneas guía internas
        c.setStrokeColorRGB(0.80, 0.80, 0.80)
        c.setLineWidth(0.3)
        # línea vertical interna a 40 pts (separa QR del texto)
        c.line(_CX[2] + 40, y_bot + 4, _CX[2] + 40, y_top - 4)
        c.setFillColorRGB(*_C_PEND)
        c.setFont("Helvetica-Oblique", 6)
        c.drawString(_CX[2] + 44, y_top - 18, "Validar únicamente en FirmaEC.")
        c.drawString(_CX[2] + 44, y_top - 30, "Firmado electrónicamente por:")
        c.setLineWidth(0.4)
        c.setStrokeColorRGB(*_C_BLACK)

    c.setFillColorRGB(*_C_BLACK)

    # ── Registrar coordenadas para pyHanko ───────────────────────
    sig_coords[campo_firma] = (
        int(_CX[2]),               # x1
        int(y_bot),                # y1 (bottom)
        int(_CX[2] + _CW[2]),     # x2
        int(y_top),                # y2 (top)
        page_num,                  # página (0-indexed)
    )


@app.route("/api/formularios/<int:formulario_id>/pdf", methods=["GET"])
def generar_pdf(formulario_id):
    conn = cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        conn    = get_connection()
        cursor  = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM formularios WHERE id = %s", (formulario_id,))
        formulario = cursor.fetchone()
        if not formulario:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        # Solo bloquear si NO es admin y el formulario no está lo suficientemente avanzado
        if user["rol"] != "Administrador" and formulario["estado"] == "BORRADOR":
            return jsonify({"mensaje": "El formulario aún está en borrador"}), 400

        # Obtener todas las respuestas indexadas por código de campo
        cursor.execute("""
            SELECT p.codigo, r.respuesta
              FROM formulario_preguntas p
              LEFT JOIN formulario_respuestas r ON p.id = r.pregunta_id
             WHERE p.formulario_id = %s
        """, (formulario_id,))
        resp_rows = cursor.fetchall()
        resp = {row["codigo"]: (row["respuesta"] or "") for row in resp_rows if row["codigo"]}

        # ── Construir el PDF ─────────────────────────────────────
        filename  = f"formulario_{formulario_id}.pdf"
        filepath  = os.path.join(UPLOAD_FOLDER, filename)
        json_path = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_sigfields.json")

        c        = canvas.Canvas(filepath, pagesize=A4)
        W, H     = A4
        y        = _MT
        page_num = 0
        sig_coords = {}

        _draw_page_header(c, formulario, page_num)

        def salto_si_necesario(needed: float) -> None:
            nonlocal y, page_num
            if y - needed < _MB:
                c.showPage()
                page_num += 1
                y = _MT
                _draw_page_header(c, formulario, page_num)

        # ── Encabezado del documento ─────────────────────────────
        salto_si_necesario(40)
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(W / 2, y - 14, "PAZ Y SALVO INSTITUCIONAL")
        y -= 22
        estado_texto = formulario.get("estado") or ""
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(*_C_PEND)
        c.drawCentredString(W / 2, y - 8, f"Estado: {estado_texto}  |  Progreso: {formulario.get('porcentaje', 0)}%")
        c.setFillColorRGB(*_C_BLACK)
        y -= 18

        # ── Datos personales ─────────────────────────────────────
        salto_si_necesario(_HH + 12)
        _draw_section_header(c, "DATOS PERSONALES Y LABORALES", y)
        y -= _HH

        campos_personales = [
            ("Nombres y Apellidos", "nombres_apellidos"),
            ("Cédula / Pasaporte",  "cedula"),
            ("Modalidad Laboral",   "modalidad"),
            ("Fecha de Ingreso",    "fecha_ingreso"),
            ("Fecha de Salida",     "fecha_salida"),
            ("Dirección / Unidad",  "unidad"),
            ("Cargo",               "cargo"),
            ("Grupo Ocupacional",   "grupo_ocupacional"),
            ("Lugar de Trabajo",    "lugar_trabajo"),
            ("Celular",             "celular"),
            ("Email Principal",     "email1"),
        ]
        col1_w, col2_w = 160, _MR - _ML - 160
        for label, campo in campos_personales:
            salto_si_necesario(_FH + 1)
            valor = resp.get(campo) or "—"
            if valor.startswith("data:"):
                valor = "[imagen]"
            c.setFillColorRGB(*_C_GRAY)
            c.rect(_ML, y - _FH, col1_w, _FH, fill=1, stroke=1)
            c.setFillColorRGB(*_C_WHITE)
            c.rect(_ML + col1_w, y - _FH, col2_w, _FH, fill=1, stroke=1)
            c.setFillColorRGB(*_C_BLACK)
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(_ML + 3, y - _FH + 4, label)
            c.setFont("Helvetica", 7.5)
            c.drawString(_ML + col1_w + 4, y - _FH + 4, str(valor)[:75])
            y -= _FH

        y -= 10  # espacio entre secciones

        # ── Secciones FirmaEC ────────────────────────────────────
        for sec in _FIRMAEC_SECTIONS:
            n_rows    = len(sec["rows"])
            # Intentar mantener encabezado + al menos 1 fila en la misma página
            salto_si_necesario(_HH + _CH + _RH)

            _draw_section_header(c, sec["titulo"], y)
            y -= _HH
            _draw_col_labels(c, y)
            y -= _CH

            for (item_text, nombre_campo, firma_campo) in sec["rows"]:
                salto_si_necesario(_RH)
                nombre_val = resp.get(nombre_campo) or ""
                firma_val  = resp.get(firma_campo)  or ""
                _draw_firma_row(
                    c, y, item_text, nombre_val, firma_val,
                    firma_campo, sig_coords, page_num
                )
                y -= _RH

            y -= 8  # espacio entre secciones

        c.save()

        # ── Guardar mapa de coordenadas ──────────────────────────
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(sig_coords, jf)

        # Si existe un PDF firmado previo, borrarlo para evitar desincronía
        signed_path = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_signed.pdf")
        if os.path.exists(signed_path):
            os.remove(signed_path)

        return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

    except Exception as e:
        return jsonify({"mensaje": "Error al generar PDF", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)
        
# ═══════════════════════════════════════════════════════════════
#  FIRMA DIGITAL EC  (pyHanko + PAdES)
# ═══════════════════════════════════════════════════════════════

@app.route("/api/formularios/<int:formulario_id>/firmar-ec", methods=["POST"])
def firmar_ec_pdf(formulario_id):
    """
    Firma digitalmente el PDF del formulario usando un certificado .p12 (FirmaEC/PKCS#12).
    Solo puede firmar el usuario que el Admin asignó a esa celda específica.

    Form-data esperado:
        campo_firma : str   – clave de la celda (ej: 'tic_r1', 'rrhh_dir')
        password    : str   – contraseña del .p12
        p12_file    : file  – archivo .p12 / .pfx
    """
    conn = cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        # ── Validar entradas ─────────────────────────────────────
        campo_firma  = (request.form.get("campo_firma") or "").strip()
        password_raw = request.form.get("password") or ""
        p12_file     = request.files.get("p12_file")

        if not campo_firma or not password_raw or not p12_file:
            return jsonify({"mensaje": "Faltan datos: campo_firma, password y p12_file son requeridos"}), 400

        ext = os.path.splitext(p12_file.filename.lower())[1]
        if ext not in (".p12", ".pfx"):
            return jsonify({"mensaje": "Solo se aceptan archivos .p12 o .pfx"}), 400

        p12_bytes = p12_file.read()
        if not p12_bytes:
            return jsonify({"mensaje": "El archivo .p12 está vacío"}), 400

        # ── Cargar y validar el certificado ANTES de tocar la BD ─
        try:
            from cryptography.hazmat.primitives.serialization.pkcs12 import (
                load_key_and_certificates,
            )
            _, certificate, _ = load_key_and_certificates(
                p12_bytes, password_raw.encode("utf-8")
            )
        except (ValueError, TypeError):
            return jsonify({"mensaje": "Contraseña incorrecta o archivo .p12 inválido/corrupto"}), 400
        except Exception as exc:
            return jsonify({"mensaje": f"No se pudo leer el certificado: {exc}"}), 400

        if certificate is None:
            return jsonify({"mensaje": "El archivo .p12 no contiene un certificado válido"}), 400

        # ── Extraer nombre del firmante del Subject del certificado ─
        from cryptography import x509
        try:
            signer_name = certificate.subject.get_attributes_for_oid(
                x509.NameOID.COMMON_NAME
            )[0].value.upper()
        except (IndexError, Exception):
            signer_name = user.get("usuario", "FIRMANTE DESCONOCIDO").upper()

        # ── Consultas a la BD ────────────────────────────────────
        conn    = get_connection()
        cursor  = conn.cursor(dictionary=True)

        cursor.execute("SELECT id, estado FROM formularios WHERE id = %s", (formulario_id,))
        formulario = cursor.fetchone()
        if not formulario:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        cursor.execute("""
            SELECT p.id AS pregunta_id,
                   a.id AS asignacion_id,
                   a.asignado_usuario_id
            FROM   formulario_preguntas p
            INNER JOIN formulario_asignaciones a ON p.id = a.pregunta_id
            WHERE  p.formulario_id = %s
              AND  p.codigo        = %s
            LIMIT  1
        """, (formulario_id, campo_firma))
        fila = cursor.fetchone()

        if not fila:
            return jsonify({"mensaje": f"La celda '{campo_firma}' no está configurada en este formulario"}), 404

        # Solo el usuario designado (o el Administrador) puede firmar
        if user["rol"] != "Administrador" and fila["asignado_usuario_id"] != user["id"]:
            return jsonify({
                "mensaje": (
                    "No tiene autorización para firmar esta celda. "
                    "Solo el usuario designado por el Administrador puede hacerlo."
                )
            }), 403

        # Verificar que no esté ya firmada
        cursor.execute("""
            SELECT id FROM formulario_respuestas
            WHERE  formulario_id = %s AND pregunta_id = %s
            LIMIT  1
        """, (formulario_id, fila["pregunta_id"]))
        if cursor.fetchone():
            return jsonify({"mensaje": "Esta celda ya fue firmada y no puede modificarse"}), 400

        # ── PDF debe existir (original o con firmas previas) ────────
        # Cadena: original → signed (acumulación incremental de firmas)
        pdf_orig   = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}.pdf")
        pdf_signed = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_signed.pdf")
        json_path  = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_sigfields.json")

        pdf_src = pdf_signed if os.path.exists(pdf_signed) else pdf_orig
        if not os.path.exists(pdf_src):
            return jsonify({
                "mensaje": (
                    "El PDF aún no existe. Genere el documento primero "
                    "usando el botón 'Descargar PDF' del formulario."
                )
            }), 400

        if not os.path.exists(json_path):
            return jsonify({
                "mensaje": (
                    "El mapa de coordenadas no existe. "
                    "Regenere el PDF con el botón 'Descargar PDF' para actualizarlo."
                )
            }), 400

        # ── Firmar con pyHanko ───────────────────────────────────
        # Destino siempre es _signed.pdf (se sobreescribe incrementalmente)
        pdf_firmado = pdf_signed
        try:
            _pyhanko_firmar(
                src_path     = pdf_src,
                dst_path     = pdf_firmado,
                p12_bytes    = p12_bytes,
                password     = password_raw,
                signer_name  = signer_name,
                campo_firma  = campo_firma,
                formulario_id= formulario_id,
                json_path    = json_path,
            )
        except RuntimeError as exc:
            return jsonify({"mensaje": str(exc)}), 400

        # ── Guardar resultado en BD ──────────────────────────────
        marca = f"FIRMADO_EC:{signer_name}:{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        cursor.execute("""
            INSERT INTO formulario_respuestas
                   (formulario_id, pregunta_id, asignacion_id, respondido_por, respuesta)
            VALUES (%s, %s, %s, %s, %s)
        """, (formulario_id, fila["pregunta_id"], fila["asignacion_id"], user["id"], marca))

        cursor.execute("""
            UPDATE formulario_asignaciones
               SET estado = 'CULMINADO', fecha_culminado = NOW()
             WHERE id = %s
        """, (fila["asignacion_id"],))

        # Recalcular porcentaje
        cursor.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN estado = 'CULMINADO' THEN 1 ELSE 0 END) AS completados
              FROM formulario_asignaciones
             WHERE formulario_id = %s
        """, (formulario_id,))
        prog        = cursor.fetchone()
        total_asig  = prog["total"]       or 0
        completados = prog["completados"] or 0
        porcentaje  = round((completados / total_asig) * 100) if total_asig > 0 else 0
        estado_form = "COMPLETADO" if porcentaje == 100 else "EN_PROCESO"

        cursor.execute(
            "UPDATE formularios SET porcentaje = %s, estado = %s WHERE id = %s",
            (porcentaje, estado_form, formulario_id)
        )
        conn.commit()

        registrar_auditoria(
            user["usuario"], user["rol"], "Formularios",
            "Firma digital EC",
            f"Firmó celda '{campo_firma}' del formulario {formulario_id} como '{signer_name}'"
        )

        return jsonify({
            "mensaje"    : "PDF firmado correctamente con su certificado FirmaEC.",
            "firmado_por": signer_name,
            "porcentaje" : porcentaje,
            "estado"     : estado_form,
        }), 200

    except Exception as exc:
        if conn:
            conn.rollback()
        return jsonify({"mensaje": "Error inesperado al firmar", "error": str(exc)}), 500
    finally:
        close_db(cursor, conn)


def _pyhanko_firmar(
    src_path: str,
    dst_path: str,
    p12_bytes: bytes,
    password: str,
    signer_name: str,
    campo_firma: str,
    formulario_id: int,
    json_path: str,
) -> None:
    """
    Firma digitalmente la celda `campo_firma` del PDF con pyHanko (PAdES).

    El sello visual ocupa EXACTAMENTE la celda de la tabla tal como la generó
    `generar_pdf` — las coordenadas se leen del archivo JSON de coordenadas.
    Todas las celdas miden 160 × 80 pts (ratio 2:1), por lo que el stamp
    PIL se genera con ratio 2:1 (320 × 160 px) para que no haya distorsión.

    Layout del sello (320 × 160 px → escala a 160 × 80 pts):
    ┌──────────────────────────────────────────────────────────────┐
    │  [QR 130×130]  │  Validar únicamente en FirmaEC.            │
    │                │  Firmado electrónicamente por:             │
    │                │  NOMBRE COMPLETO DEL FIRMANTE              │
    └──────────────────────────────────────────────────────────────┘
    """
    import io as _io

    # ── Dependencias opcionales ──────────────────────────────────
    try:
        import qrcode
        from PIL import Image, ImageDraw
    except ImportError:
        raise RuntimeError("pip install qrcode[pil] Pillow")

    try:
        from pyhanko.sign import signers, fields as sign_fields
        from pyhanko.sign.signers.pdf_signer import PdfSignatureMetadata
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    except ImportError:
        raise RuntimeError("pip install pyhanko pyhanko-certvalidator")

    # ── Cargar firmante desde PKCS#12 ────────────────────────────
    try:
        signer = signers.SimpleSigner.load_pkcs12(
            pfx_file   = _io.BytesIO(p12_bytes),
            passphrase = password.encode("utf-8"),
        )
    except Exception:
        raise RuntimeError("Contraseña del .p12 incorrecta o certificado dañado.")

    # ── Leer coordenadas del JSON generado por generar_pdf ───────
    try:
        with open(json_path, "r", encoding="utf-8") as jf:
            sig_map = json.load(jf)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo leer el mapa de coordenadas: {exc}")

    if campo_firma not in sig_map:
        raise RuntimeError(
            f"La celda '{campo_firma}' no tiene coordenadas registradas. "
            "Regenere el PDF para actualizar el mapa."
        )

    coords   = sig_map[campo_firma]          # [x1, y1, x2, y2, page]
    SIG_BOX  = (coords[0], coords[1], coords[2], coords[3])
    SIG_PAGE = int(coords[4])                # 0-indexed

    # ── Construir imagen del sello FirmaEC  (ratio 2:1 fijo) ─────
    # 320 × 160 px → pyHanko escala al box → sin distorsión
    IMG_W, IMG_H = 320, 160
    QR_SIZE      = 130    # QR cuadrado, centrado verticalmente
    DIV_X        = QR_SIZE + 10   # x de la línea divisoria
    TX           = DIV_X + 8      # x del texto

    stamp = Image.new("RGB", (IMG_W, IMG_H), "white")
    draw  = ImageDraw.Draw(stamp)

    # QR con URL de validación FirmaEC
    qr_url = (
        f"https://validar.firmaec.ec/"
        f"?id={formulario_id}&campo={campo_firma}"
    )
    qr = qrcode.QRCode(
        version          = 2,
        box_size         = 4,
        border           = 1,
        error_correction = qrcode.constants.ERROR_CORRECT_M,
    )
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_img = qr_img.resize((QR_SIZE, QR_SIZE), Image.LANCZOS)
    stamp.paste(qr_img, (6, (IMG_H - QR_SIZE) // 2))

    # Línea divisoria vertical
    draw.line([(DIV_X, 8), (DIV_X, IMG_H - 8)], fill="#666666", width=1)

    # Texto — tres líneas alineadas a la izquierda del área de texto
    draw.text((TX, 18),  "Validar únicamente en FirmaEC.", fill="#003087")
    draw.text((TX, 68),  "Firmado electrónicamente por:",  fill="#444444")
    # Nombre del firmante: truncar si supera el ancho disponible
    nombre_disp = signer_name[:30] if len(signer_name) > 30 else signer_name
    draw.text((TX, 112), nombre_disp,                      fill="#000000")

    # Borde exterior
    draw.rectangle([1, 1, IMG_W - 2, IMG_H - 2], outline="#AAAAAA", width=1)

    stamp_buf = _io.BytesIO()
    stamp.save(stamp_buf, format="PNG")
    stamp_buf.seek(0)

    # ── Escribir PDF firmado (incremental) ───────────────────────
    # Si src == dst (firma sobre firmado previo), usar buffer intermedio
    use_tmp = (src_path == dst_path)
    if use_tmp:
        with open(src_path, "rb") as f_in:
            src_bytes = f_in.read()
        in_stream = _io.BytesIO(src_bytes)
    else:
        in_stream = open(src_path, "rb")

    FIELD_NAME = f"Sig_{campo_firma}"

    try:
        writer = IncrementalPdfFileWriter(in_stream)

        sign_fields.append_signature_field(
            writer,
            sig_field_spec=sign_fields.SigFieldSpec(
                sig_field_name = FIELD_NAME,
                box            = SIG_BOX,
                on_page        = SIG_PAGE,
            ),
        )

        meta = PdfSignatureMetadata(
            field_name = FIELD_NAME,
            reason     = f"Paz y Salvo INAMHI — {campo_firma}",
            location   = "Ecuador",
            name       = signer_name,
            certify    = False,
        )

        out_buf = _io.BytesIO()
        signers.sign_pdf(
            writer,
            signature_meta     = meta,
            signer             = signer,
            output             = out_buf,
            existing_fields_only = False,
        )
    finally:
        if not use_tmp:
            in_stream.close()

    # Escribir resultado
    with open(dst_path, "wb") as f_out:
        f_out.write(out_buf.getvalue())


if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True, use_reloader=False)