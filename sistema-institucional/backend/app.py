from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from mysql.connector import pooling
import mysql.connector
import jwt
import datetime
import os
import re

app = Flask(__name__)

app.config["SECRET_KEY"] = "clave_super_secreta_inamhi_2026_segura"
CORS(app, resources={r"/api/*": {"origins": "*"}})

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

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def limpiar_texto(texto):
    return re.sub(r"\s+", " ", (texto or "").strip())

def solo_letras(texto):
    return bool(re.match(r"^[a-zA-ZÁÉÍÓÚáéíóúÑñ\s]+$", texto or ""))

def normalizar_usuario(texto):
    texto = (texto or "").strip().lower()
    texto = texto.replace("á", "a").replace("é", "e").replace("í", "i")
    texto = texto.replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    texto = re.sub(r"[^a-z0-9._-]", "", texto)
    return texto

def generar_usuario(nombres, apellidos):
    nombres = normalizar_usuario(nombres)
    apellidos = normalizar_usuario(apellidos).replace(" ", "")
    if not nombres or not apellidos:
        return ""
    return nombres[0] + apellidos

def obtener_usuario_token():
    token = request.headers.get("Authorization")

    if not token:
        return None

    token = token.replace("Bearer ", "")

    try:
        data = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        return {
            "id": data["id"],
            "usuario": data["usuario"],
            "rol": data["rol"]
        }
    except Exception:
        return None

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

        #----registrar_auditoria(
        #    user["usuario"],
        #    user["rol"],
         #   "Login",
         #   "Inicio de sesión",
         #   f"Usuario {user['usuario']} inició sesión"
        #)

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
    return jsonify([{"nombre": r} for r in ROLES_VALIDOS]), 200

@app.route("/api/usuarios", methods=["GET"])
def listar_usuarios():
    conn = None
    cursor = None

    try:
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

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
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

        if user_token["rol"] != "Administrador":
            return jsonify({"mensaje": "No tiene permisos"}), 403

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
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

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
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

        if user_token["rol"] != "Administrador":
            return jsonify({"mensaje": "No tiene permisos"}), 403

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
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

        if user_token["rol"] != "Administrador":
            return jsonify({"mensaje": "No tiene permisos"}), 403

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
    return send_from_directory(UPLOAD_FOLDER, nombre)

@app.route("/api/documentos/descargar/<path:nombre>", methods=["GET"])
def descargar_archivo(nombre):
    return send_from_directory(UPLOAD_FOLDER, nombre, as_attachment=True)

@app.route("/api/documentos", methods=["GET"])
def listar_documentos():
    conn = None
    cursor = None

    try:
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

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
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

        titulo = limpiar_texto(request.form.get("titulo"))
        descripcion = limpiar_texto(request.form.get("descripcion"))
        estado = request.form.get("estado", "BORRADOR")
        creado_por = request.form.get("creado_por") or user_token["id"]

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
            creado_por,
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

@app.route("/api/documentos/<int:id>", methods=["PUT"])
def actualizar_documento(id):
    conn = None
    cursor = None

    try:
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

        if user_token["rol"] != "Administrador":
            return jsonify({"mensaje": "No tiene permisos"}), 403

        data = request.get_json(silent=True) or {}

        titulo = limpiar_texto(data.get("titulo"))
        descripcion = limpiar_texto(data.get("descripcion"))
        estado = data.get("estado")

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
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

        if user_token["rol"] != "Administrador":
            return jsonify({"mensaje": "No tiene permisos"}), 403

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
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

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

@app.route("/api/auditoria", methods=["GET"])
def listar_auditoria():
    conn = None
    cursor = None

    try:
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

        if user_token["rol"] != "Administrador":
            return jsonify({"mensaje": "No tiene permisos"}), 403

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

@app.route("/api/reportes/estado-documentos", methods=["GET"])
def reporte_estado_documentos():
    conn = None
    cursor = None

    try:
        user_token = obtener_usuario_token()

        if not user_token:
            return jsonify({"mensaje": "No autorizado"}), 401

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

if __name__ == "__main__":
    app.run(debug=True, port=5000, threaded=True, use_reloader=False) 