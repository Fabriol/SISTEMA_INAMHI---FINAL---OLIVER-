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

        return jsonify(cursor.fetchall()), 200
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
        respuesta = limpiar_texto(data.get("respuesta"))

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
        return jsonify({"mensaje": "Error al guardar campo", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)


@app.route("/api/formularios/<int:formulario_id>/pdf", methods=["GET"])
def generar_pdf(formulario_id):
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
            FROM formularios
            WHERE id = %s
        """, (formulario_id,))
        formulario = cursor.fetchone()

        if not formulario:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        if formulario["estado"] != "COMPLETADO":
            return jsonify({"mensaje": "Formulario aún no está completo"}), 400

        cursor.execute("""
            SELECT p.pregunta, r.respuesta
            FROM formulario_preguntas p
            LEFT JOIN formulario_asignaciones a ON p.id = a.pregunta_id
            LEFT JOIN formulario_respuestas r ON a.id = r.asignacion_id
            WHERE p.formulario_id = %s
            ORDER BY p.orden ASC, p.id ASC
        """, (formulario_id,))

        data = cursor.fetchall()

        filename = f"formulario_{formulario_id}.pdf"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        c = canvas.Canvas(filepath, pagesize=A4)
        width, height = A4

        y = height - 40

        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, y, formulario["titulo"])
        y -= 20

        c.setFont("Helvetica", 10)
        c.drawString(40, y, formulario.get("descripcion") or "")
        y -= 30

        for item in data:
            pregunta = item.get("pregunta", "")
            respuesta = item.get("respuesta") or "Sin respuesta"

            c.setFont("Helvetica-Bold", 10)
            c.drawString(40, y, f"P: {pregunta[:80]}")
            y -= 15

            c.setFont("Helvetica", 10)
            c.drawString(60, y, f"R: {respuesta[:90]}")
            y -= 20

            if y < 50:
                c.showPage()
                y = height - 40

        c.save()

        return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

    except Exception as e:
        return jsonify({"mensaje": "Error al generar PDF", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)
        
if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True, use_reloader=False)