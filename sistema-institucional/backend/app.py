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

def _ensure_schema():
    """Ajusta columnas del esquema para soportar todos los tipos de datos necesarios."""
    conn = cursor = None
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # 1. formulario_respuestas.respuesta → MEDIUMTEXT (para base64 de firmas)
        cursor.execute("""
            SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = 'formulario_respuestas'
              AND COLUMN_NAME  = 'respuesta'
        """)
        row = cursor.fetchone()
        if row and row[0].lower() not in ('mediumtext', 'longtext'):
            cursor.execute(
                "ALTER TABLE formulario_respuestas MODIFY COLUMN respuesta MEDIUMTEXT"
            )
            print("[startup] formulario_respuestas.respuesta → MEDIUMTEXT OK")
        elif not row:
            print("[startup] ADVERTENCIA: columna formulario_respuestas.respuesta no encontrada")

        # 2. formulario_preguntas.tipo → VARCHAR(30) (para aceptar 'FIRMA' y otros)
        cursor.execute("""
            SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = 'formulario_preguntas'
              AND COLUMN_NAME  = 'tipo'
        """)
        row2 = cursor.fetchone()
        if row2 and row2[0].lower() == 'enum':
            cursor.execute(
                "ALTER TABLE formulario_preguntas MODIFY COLUMN tipo VARCHAR(30) NOT NULL DEFAULT 'TEXTO'"
            )
            print("[startup] formulario_preguntas.tipo → VARCHAR(30) OK")

        # 3. formularios.observacion → TEXT (observación de rechazo / revisión)
        cursor.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = 'formularios'
              AND COLUMN_NAME  = 'observacion'
        """)
        if not cursor.fetchone():
            cursor.execute(
                "ALTER TABLE formularios ADD COLUMN observacion TEXT NULL DEFAULT NULL"
            )
            print("[startup] formularios.observacion → TEXT OK")

        # 4. formularios.revisado_por → VARCHAR(120) (quien hizo la acción final)
        cursor.execute("""
            SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME   = 'formularios'
              AND COLUMN_NAME  = 'revisado_por'
        """)
        if not cursor.fetchone():
            cursor.execute(
                "ALTER TABLE formularios ADD COLUMN revisado_por VARCHAR(120) NULL DEFAULT NULL"
            )
            print("[startup] formularios.revisado_por → VARCHAR OK")

        conn.commit()
    except Exception as e:
        print(f"[startup] _ensure_schema error: {e}")
    finally:
        close_db(cursor, conn)


def _habilitar_openssl_legacy():
    """
    Habilita el proveedor 'legacy' de OpenSSL 3.x.

    Los certificados FirmaEC Ecuador (ANF, Security Data, BCE, etc.) usan
    RC2-40-CBC / 3DES para cifrar las claves privadas dentro del PKCS#12.
    OpenSSL ≥ 3.0 mueve esos algoritmos al proveedor 'legacy', que por
    defecto viene desactivado.  Sin este paso, load_key_and_certificates()
    y SimpleSigner.load_pkcs12() lanzan errores aunque la contraseña sea
    correcta.

    Métodos probados en orden hasta que uno funcione:
      1. cryptography backend directo (más portable)
      2. ctypes sobre libssl (fallback)
    """
    # ── Método 1: usar el backend interno de cryptography ──────
    try:
        from cryptography.hazmat.backends.openssl import backend as _ssl_backend
        _lib = _ssl_backend._lib
        _ffi = _ssl_backend._ffi
        if hasattr(_lib, 'OSSL_PROVIDER_load'):
            _prov_legacy = _lib.OSSL_PROVIDER_load(_ffi.NULL, b'legacy')
            _lib.OSSL_PROVIDER_load(_ffi.NULL, b'default')
            if _prov_legacy != _ffi.NULL:
                print("[startup] OpenSSL legacy provider habilitado (vía cryptography backend) ✓")
                return
    except Exception as _e1:
        print(f"[startup] legacy método 1 falló: {_e1}")

    # ── Método 2: ctypes directamente sobre libssl ─────────────
    try:
        import ctypes, ctypes.util
        _libssl = None
        # Probar nombres comunes en Windows, Linux y macOS
        _ssl_names = [
            'libssl-3-x64.dll', 'libssl-3.dll', 'libssl.dll',   # Windows
            ctypes.util.find_library('ssl') or '',               # Linux/macOS via ldconfig
            'libssl.so.3', 'libssl.so.1.1', 'libssl.dylib',     # fallback
        ]
        for _dll in _ssl_names:
            if not _dll:
                continue
            try:
                _libssl = ctypes.CDLL(_dll)
                break
            except Exception:
                continue

        if _libssl and hasattr(_libssl, 'OSSL_PROVIDER_load'):
            _libssl.OSSL_PROVIDER_load.restype  = ctypes.c_void_p
            _libssl.OSSL_PROVIDER_load.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            _libssl.OSSL_PROVIDER_load(None, b'legacy')
            _libssl.OSSL_PROVIDER_load(None, b'default')
            print("[startup] OpenSSL legacy provider habilitado (vía ctypes) ✓")
            return
    except Exception as _e2:
        print(f"[startup] legacy método 2 falló: {_e2}")

    # ── Método 3 (Windows): buscar ossl-modules en instalaciones conocidas ──
    # Git for Windows incluye OpenSSL 3.x con legacy.dll. Apuntamos OPENSSL_MODULES
    # a ese directorio para que el proveedor legacy sea encontrado al llamar
    # OSSL_PROVIDER_load desde el backend de cryptography.
    try:
        import sys as _sys2, os as _os2
        if _sys2.platform == 'win32':
            _ossl_mod_candidates = [
                r'C:\Program Files\Git\mingw64\lib\ossl-modules',
                r'C:\Program Files (x86)\Git\mingw64\lib\ossl-modules',
                r'C:\OpenSSL-Win64\lib\ossl-modules',
                r'C:\OpenSSL-Win32\lib\ossl-modules',
                r'C:\OpenSSL\lib\ossl-modules',
            ]
            for _cand in _ossl_mod_candidates:
                if _os2.path.isfile(_os2.path.join(_cand, 'legacy.dll')):
                    _os2.environ['OPENSSL_MODULES'] = _cand
                    try:
                        from cryptography.hazmat.backends.openssl import backend as _ssl_b3
                        _lib3 = _ssl_b3._lib
                        _ffi3 = _ssl_b3._ffi
                        if hasattr(_lib3, 'OSSL_PROVIDER_load'):
                            _prov3 = _lib3.OSSL_PROVIDER_load(_ffi3.NULL, b'legacy')
                            _lib3.OSSL_PROVIDER_load(_ffi3.NULL, b'default')
                            if _prov3 != _ffi3.NULL:
                                print(f"[startup] OpenSSL legacy provider habilitado "
                                      f"(OPENSSL_MODULES={_cand}) ✓")
                                return
                    except Exception as _e3i:
                        print(f"[startup] legacy método 3 falló para {_cand}: {_e3i}")
                    break
    except Exception as _e3:
        print(f"[startup] legacy método 3 falló: {_e3}")

    print("[startup] ADVERTENCIA: no se pudo habilitar el proveedor legacy de OpenSSL. "
          "Los certificados FirmaEC con RC2/3DES podrían no cargarse.")


_habilitar_openssl_legacy()


def close_db(cursor=None, conn=None):
    try:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
    except Exception as e:
        print("Error cerrando conexión:", e)

try:
    _ensure_schema()
except Exception as e:
    print(f"[startup] _ensure_schema excepción: {e}") 

def limpiar_texto(texto):
    if texto is None:
        return ""
    return re.sub(r"\s+", " ", str(texto).strip())

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

@app.route("/api/reportes/formularios-pendientes", methods=["GET"])
def reportes_formularios_pendientes():
    """
    Devuelve formularios con sus asignaciones pendientes.
    Accesible para Administrador y Talento Humano - Recepcion Documentos.
    """
    conn   = None
    cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        rol_raw  = str(user.get("rol") or "")
        rol_norm = rol_raw.lower().strip()
        es_admin = rol_raw == "Administrador"
        es_th    = ("talento humano" in rol_norm) and ("recep" in rol_norm)

        if not es_admin and not es_th:
            return jsonify({"mensaje": "Acceso denegado"}), 403

        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # ── Una sola query que trae todo: formulario + usuario + sus conteos ──
        cursor.execute("""
            SELECT
                f.id                                                            AS formulario_id,
                f.titulo,
                f.estado                                                        AS formulario_estado,
                COALESCE(f.porcentaje, 0)                                       AS porcentaje,
                u.id                                                            AS usuario_id,
                CONCAT(TRIM(u.nombres), ' ', TRIM(u.apellidos))                 AS nombre_completo,
                u.nombres,
                u.apellidos,
                u.usuario,
                COUNT(a.id)                                                     AS total_asignados,
                SUM(CASE WHEN a.estado = 'CULMINADO'  THEN 1 ELSE 0 END)        AS completados,
                SUM(CASE WHEN a.estado != 'CULMINADO' THEN 1 ELSE 0 END)        AS pendientes
            FROM formulario_asignaciones a
            INNER JOIN formularios  f ON f.id = a.formulario_id
            INNER JOIN usuarios     u ON u.id = a.asignado_usuario_id
            GROUP BY
                f.id, f.titulo, f.estado, f.porcentaje,
                u.id, u.nombres, u.apellidos, u.usuario
            HAVING SUM(CASE WHEN a.estado != 'CULMINADO' THEN 1 ELSE 0 END) > 0
            ORDER BY f.id DESC, pendientes DESC
        """)
        filas = cursor.fetchall()

        # ── Agrupar por formulario en Python (más simple y sin problema de cursor) ──
        formularios_map: dict = {}
        for fila in filas:
            fid = fila["formulario_id"]
            if fid not in formularios_map:
                formularios_map[fid] = {
                    "id":                 fid,
                    "titulo":             fila["titulo"],
                    "estado":             fila["formulario_estado"],
                    "porcentaje":         int(fila["porcentaje"] or 0),
                    "total_campos":       0,
                    "completados":        0,
                    "pendientes":         0,
                    "usuarios_pendientes": [],
                }

            formularios_map[fid]["total_campos"] += int(fila["total_asignados"] or 0)
            formularios_map[fid]["completados"]  += int(fila["completados"]      or 0)
            formularios_map[fid]["pendientes"]   += int(fila["pendientes"]       or 0)
            formularios_map[fid]["usuarios_pendientes"].append({
                "usuario_id":     fila["usuario_id"],
                "nombre_completo": fila["nombre_completo"],
                "nombres":        fila["nombres"],
                "apellidos":      fila["apellidos"],
                "usuario":        fila["usuario"],
                "total_asignados": int(fila["total_asignados"] or 0),
                "completados":    int(fila["completados"]       or 0),
                "pendientes":     int(fila["pendientes"]        or 0),
            })

        resultado = list(formularios_map.values())
        return jsonify(resultado), 200

    except Exception as e:
        print("[ERROR /reportes/formularios-pendientes]", traceback.format_exc())
        return jsonify({"mensaje": "Error al cargar reporte", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)


@app.route("/api/reportes/enviar-recordatorio", methods=["POST"])
def enviar_recordatorio():
    """
    Envía una notificación de recordatorio a un usuario con campos pendientes.
    Accesible para Administrador y Talento Humano - Recepcion Documentos.
    """
    conn = None
    cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        rol_norm = user["rol"].lower().strip()
        es_admin = user["rol"] == "Administrador"
        es_th    = "talento humano" in rol_norm and "recep" in rol_norm

        if not es_admin and not es_th:
            return jsonify({"mensaje": "Acceso denegado"}), 403

        data          = request.get_json(silent=True) or {}
        usuario_id    = data.get("usuario_id")
        formulario_id = data.get("formulario_id")
        mensaje_extra = limpiar_texto(data.get("mensaje", ""))

        if not usuario_id or not formulario_id:
            return jsonify({"mensaje": "Datos incompletos: usuario_id y formulario_id requeridos"}), 400

        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Verificar que el usuario y formulario existen
        cursor.execute("SELECT id, nombres, apellidos FROM usuarios WHERE id = %s AND estado = 'ACTIVO'", (usuario_id,))
        dest = cursor.fetchone()
        if not dest:
            return jsonify({"mensaje": "Usuario destino no encontrado o inactivo"}), 404

        cursor.execute("SELECT id, titulo FROM formularios WHERE id = %s", (formulario_id,))
        form = cursor.fetchone()
        if not form:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        # Contar campos pendientes de ese usuario en ese formulario
        cursor.execute("""
            SELECT COUNT(*) AS pendientes
            FROM formulario_asignaciones
            WHERE formulario_id = %s AND asignado_usuario_id = %s AND estado != 'CULMINADO'
        """, (formulario_id, usuario_id))
        pend = cursor.fetchone()
        n_pendientes = pend["pendientes"] if pend else 0

        nombre_dest = f"{dest['nombres']} {dest['apellidos']}".strip()
        remitente   = user["usuario"]

        titulo_notif = f"Recordatorio: tienes {n_pendientes} campo(s) pendiente(s)"
        msg_notif    = (
            f"El formulario «{form['titulo']}» tiene {n_pendientes} campo(s) sin completar "
            f"asignados a ti. Por favor ingresa al sistema y completa la información. "
            f"Recordatorio enviado por: {remitente}."
        )
        if mensaje_extra:
            msg_notif += f" Mensaje adicional: {mensaje_extra}"

        cursor.execute("""
            INSERT INTO notificaciones (usuario_id, rol_destino, titulo, mensaje, leido)
            VALUES (%s, NULL, %s, %s, 0)
        """, (usuario_id, titulo_notif, msg_notif))

        conn.commit()

        registrar_auditoria(
            user["usuario"], user["rol"], "Reportes",
            "Recordatorio enviado",
            f"Recordatorio a {nombre_dest} (ID {usuario_id}) por formulario {formulario_id} — {n_pendientes} pendientes"
        )

        return jsonify({
            "mensaje": f"Recordatorio enviado correctamente a {nombre_dest}.",
            "pendientes": n_pendientes
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()
        print("[ERROR /reportes/enviar-recordatorio]", traceback.format_exc())
        return jsonify({"mensaje": "Error al enviar recordatorio", "error": str(e)}), 500
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
            SELECT
                a.*,
                COALESCE(
                    CONCAT(TRIM(u.nombres), ' ', TRIM(u.apellidos)),
                    a.usuario
                ) AS nombre_completo
            FROM auditoria a
            LEFT JOIN usuarios u ON a.usuario = u.usuario
            ORDER BY a.id DESC
            LIMIT 500
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


@app.route("/api/formularios/<int:id>/estado", methods=["PATCH"])
def cambiar_estado_formulario(id):
    """
    Talento Humano - Recepcion Documentos define el estado final:
    APROBADO → inhabilita al ex funcionario asignado
    EN_REVISION → queda pendiente de revisión
    NEGADO → requiere observacion obligatoria
    """
    conn = cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        data = request.get_json(silent=True) or {}
        nuevo_estado = (data.get("estado") or "").strip().upper()
        observacion  = limpiar_texto(data.get("observacion") or "")

        if nuevo_estado not in ("APROBADO", "EN_REVISION", "NEGADO"):
            return jsonify({"mensaje": "Estado inválido. Use APROBADO, EN_REVISION o NEGADO"}), 400

        if nuevo_estado == "NEGADO" and not observacion:
            return jsonify({"mensaje": "La observación es obligatoria al negar un formulario"}), 400

        conn    = get_connection()
        cursor  = conn.cursor(dictionary=True)

        cursor.execute("SELECT id, porcentaje, creado_por FROM formularios WHERE id = %s", (id,))
        formulario = cursor.fetchone()
        if not formulario:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        if nuevo_estado == "APROBADO" and (formulario["porcentaje"] or 0) < 100:
            return jsonify({"mensaje": "El formulario no está completo al 100%"}), 400

        cursor.execute("""
            UPDATE formularios
            SET estado = %s, observacion = %s, revisado_por = %s
            WHERE id = %s
        """, (nuevo_estado, observacion if nuevo_estado == "NEGADO" else None,
              user["usuario"], id))

        usuario_inhabilitado = None
        if nuevo_estado == "APROBADO":
            # Encontrar al ex funcionario asignado al formulario
            cursor.execute("""
                SELECT DISTINCT u.id, u.usuario, u.nombres, u.apellidos
                FROM formulario_asignaciones a
                INNER JOIN usuarios u ON a.asignado_usuario_id = u.id
                WHERE a.formulario_id = %s
                  AND LOWER(u.rol) LIKE '%ex%funcionario%'
                LIMIT 1
            """, (id,))
            ex_func = cursor.fetchone()
            if ex_func:
                cursor.execute(
                    "UPDATE usuarios SET estado = 'INHABILITADO' WHERE id = %s",
                    (ex_func["id"],)
                )
                usuario_inhabilitado = f"{ex_func['nombres']} (ID {ex_func['id']})"

        conn.commit()

        registrar_auditoria(
            user["usuario"], user["rol"], "Formularios",
            f"Estado final: {nuevo_estado}",
            f"Formulario {id} → {nuevo_estado}"
            + (f" | Obs: {observacion}" if observacion else "")
            + (f" | Usuario inhabilitado: {usuario_inhabilitado}" if usuario_inhabilitado else "")
        )

        msg = {
            "APROBADO":    "Formulario aprobado. El ex funcionario ha sido inhabilitado.",
            "EN_REVISION": "Formulario marcado en revisión.",
            "NEGADO":      "Formulario negado. El ex funcionario ha sido notificado.",
        }[nuevo_estado]

        return jsonify({
            "mensaje": msg,
            "estado":  nuevo_estado,
            "usuario_inhabilitado": usuario_inhabilitado
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()
        print("[ERROR /estado]", traceback.format_exc())
        return jsonify({"mensaje": "Error al cambiar estado", "error": str(e)}), 500
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

                tipo_raw = limpiar_texto(campo.get("tipo") or "TEXTO").upper()
                # Tipos reconocidos; cualquier valor desconocido se guarda como TEXTO
                TIPOS_VALIDOS = {"TEXTO", "NUMERO", "FECHA", "SELECT", "TEXTAREA", "CHECKBOX", "FIRMA"}
                tipo = tipo_raw if tipo_raw in TIPOS_VALIDOS else "TEXTO"
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
    import mysql.connector

    conn = None
    cursor = None

    try:
        user, error = validar_login()
        if error:
            return error

        data = request.get_json(silent=True) or {}

        formulario_id = data.get("formulario_id")
        campo         = limpiar_texto(data.get("campo"))
        respuesta_raw = data.get("respuesta")

        # Conservar base64 de firma intacto; convertir el resto a string limpio
        if isinstance(respuesta_raw, str) and respuesta_raw.startswith("data:"):
            respuesta = respuesta_raw
        elif isinstance(respuesta_raw, str) and respuesta_raw.upper().startswith("FIRMADO_EC:"):
            respuesta = respuesta_raw
        else:
            respuesta = limpiar_texto(respuesta_raw)

        if not formulario_id or not campo:
            return jsonify({"mensaje": "Datos incompletos: falta formulario_id o campo"}), 400

        if respuesta == "" or respuesta is None:
            return jsonify({"mensaje": "Datos incompletos: respuesta vacía"}), 400

        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # ── 1. Buscar la pregunta por código (exacto, luego insensible a mayúsculas) ──
        cursor.execute("""
            SELECT id FROM formulario_preguntas
            WHERE formulario_id = %s AND codigo = %s
            LIMIT 1
        """, (formulario_id, campo))
        pregunta = cursor.fetchone()

        if not pregunta:
            # Fallback: búsqueda insensible a mayúsculas/minúsculas
            cursor.execute("""
                SELECT id FROM formulario_preguntas
                WHERE formulario_id = %s AND LOWER(TRIM(codigo)) = LOWER(TRIM(%s))
                LIMIT 1
            """, (formulario_id, campo))
            pregunta = cursor.fetchone()

        if not pregunta:
            # Último intento: crear la pregunta si la asignación existe (estado inconsistente)
            cursor.execute("""
                SELECT a.id AS asig_id
                FROM formulario_asignaciones a
                WHERE a.formulario_id = %s AND a.asignado_usuario_id = %s
                LIMIT 1
            """, (formulario_id, user["id"]))
            asig_check = cursor.fetchone()

            if asig_check:
                # El admin asignó este campo pero la pregunta no existe: auto-crear
                cursor.execute("""
                    INSERT INTO formulario_preguntas
                    (formulario_id, codigo, pregunta, tipo, seccion, opciones, obligatorio, orden)
                    VALUES (%s, %s, %s, 'TEXTO', 'GENERAL', NULL, 0, 0)
                """, (formulario_id, campo, campo))
                pregunta = {"id": cursor.lastrowid}
                print(f"[INFO /responder] Auto-creada pregunta '{campo}' para formulario {formulario_id}")
            else:
                print(f"[WARN /responder] Campo '{campo}' no encontrado en formulario {formulario_id}")
                return jsonify({"mensaje": f"Campo '{campo}' no encontrado en el formulario"}), 404

        pregunta_id = pregunta["id"]

        # ── 2. Buscar la asignación del usuario ─────────────────
        cursor.execute("""
            SELECT id, estado FROM formulario_asignaciones
            WHERE formulario_id = %s
              AND pregunta_id = %s
              AND asignado_usuario_id = %s
            LIMIT 1
        """, (formulario_id, pregunta_id, user["id"]))
        asignacion = cursor.fetchone()

        if user["rol"] != "Administrador" and not asignacion:
            return jsonify({"mensaje": "Este campo no fue asignado a usted"}), 403

        asignacion_id = asignacion["id"] if asignacion else None

        # ── 3. Verificar si ya existe respuesta ─────────────────
        cursor.execute("""
            SELECT id FROM formulario_respuestas
            WHERE formulario_id = %s AND pregunta_id = %s
            LIMIT 1
        """, (formulario_id, pregunta_id))
        ya_respondido = cursor.fetchone()

        if ya_respondido:
            return jsonify({"mensaje": "Este campo ya fue llenado y no se puede editar."}), 400

        # ── 4. Insertar respuesta ────────────────────────────────
        try:
            cursor.execute("""
                INSERT INTO formulario_respuestas
                (formulario_id, pregunta_id, asignacion_id, respondido_por, respuesta)
                VALUES (%s, %s, %s, %s, %s)
            """, (formulario_id, pregunta_id, asignacion_id, user["id"], respuesta))
        except mysql.connector.errors.IntegrityError as ie:
            # Llave duplicada: la respuesta ya fue guardada en otra sesión simultánea
            conn.rollback()
            return jsonify({"mensaje": "Este campo ya fue llenado y no se puede editar."}), 400
        except mysql.connector.errors.DataError as de:
            conn.rollback()
            print(f"[ERROR /responder] DataError campo='{campo}': {de}")
            return jsonify({"mensaje": f"El valor del campo '{campo}' es demasiado largo o tiene formato inválido.", "error": str(de)}), 400

        # ── 5. Marcar asignación como culminada ──────────────────
        if asignacion_id:
            cursor.execute("""
                UPDATE formulario_asignaciones
                SET estado = 'CULMINADO', fecha_culminado = NOW()
                WHERE id = %s
            """, (asignacion_id,))

        # ── 6. Recalcular porcentaje ─────────────────────────────
        TOTAL_CAMPOS_ESPEJO = 147
        cursor.execute("""
            SELECT COUNT(*) AS completados
            FROM formulario_asignaciones
            WHERE formulario_id = %s AND estado = 'CULMINADO'
        """, (formulario_id,))
        progreso    = cursor.fetchone()
        completados = progreso["completados"] or 0
        porcentaje  = min(round((completados / TOTAL_CAMPOS_ESPEJO) * 100), 100)
        estado_form = "COMPLETADO" if completados >= TOTAL_CAMPOS_ESPEJO else "EN_PROCESO"

        # UPDATE con reintento automático ante deadlock (error 1213)
        import time as _time
        _max_reintentos = 4
        for _intento in range(_max_reintentos):
            try:
                cursor.execute("""
                    UPDATE formularios SET porcentaje = %s, estado = %s WHERE id = %s
                """, (porcentaje, estado_form, formulario_id))
                break
            except mysql.connector.errors.InternalError as _de:
                if getattr(_de, 'errno', None) == 1213 and _intento < _max_reintentos - 1:
                    conn.rollback()
                    _time.sleep(0.08 * (_intento + 1))
                    # Reconectar y reiniciar la transacción
                    close_db(cursor, conn)
                    conn   = get_connection()
                    cursor = conn.cursor(dictionary=True)
                    # Re-marcar asignación como culminada y re-calcular porcentaje
                    if asignacion_id:
                        cursor.execute("""
                            UPDATE formulario_asignaciones
                            SET estado = 'CULMINADO', fecha_culminado = NOW()
                            WHERE id = %s
                        """, (asignacion_id,))
                    cursor.execute("""
                        SELECT COUNT(*) AS completados
                        FROM formulario_asignaciones
                        WHERE formulario_id = %s AND estado = 'CULMINADO'
                    """, (formulario_id,))
                    _prog   = cursor.fetchone()
                    completados = _prog["completados"] or 0
                    porcentaje  = min(round((completados / TOTAL_CAMPOS_ESPEJO) * 100), 100)
                    estado_form = "COMPLETADO" if completados >= TOTAL_CAMPOS_ESPEJO else "EN_PROCESO"
                    continue
                raise

        conn.commit()

        return jsonify({
            "mensaje": "Campo guardado correctamente",
            "porcentaje": porcentaje,
            "estado": estado_form
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()
        print("[ERROR /responder]", traceback.format_exc())
        return jsonify({"mensaje": "Error interno al guardar campo", "error": str(e)}), 500

    finally:
        close_db(cursor, conn)


# ═══════════════════════════════════════════════════════════════
#  PDF PAZ Y SALVO — HOJA ESPEJO (idéntico al frontend Angular)
# ═══════════════════════════════════════════════════════════════
#  A4 = 595.28 × 841.89 pts.  Origen (0,0) = esquina inferior-izquierda.

# ── Márgenes ─────────────────────────────────────────────────────────────────
_ML  = 30          # margen izquierdo
_MR  = 565         # margen derecho (595 - 30)
_CW  = 535         # ancho de contenido
_MT  = 782         # Y inicial bajo el header institucional
_MB  = 50          # Y mínima antes de salto de página

# ── Columna FIRMA: siempre la última a la derecha (22% de _CW) ───────────────
_FX1 = 448          # x izquierdo de la columna firma
_FX2 = 565          # x derecho
_FW  = 117          # ancho de la columna firma
_FRH = 55           # altura de fila firma

# ── Tablas 6-col: Trámites y Seguridad (HTML: 22|5|22|5|24|22 %) ─────────────
_T6W = [118, 27, 118, 27, 128, 117]
_T6X = [30, 148, 175, 293, 320, 448]
_T6L = ["DESCRIPCIÓN", "S/N", "DESCRIPCIÓN", "S/N",
        "NOMBRE RESPONSABLE", "FIRMA ELECTRÓNICA"]

# ── Tablas 5-col: Admin, TIC, Fin, RRHH (HTML: 29|5|22|22|22 %) ─────────────
_T5W = [155, 27, 118, 118, 117]
_T5X = [30, 185, 212, 330, 448]
_T5L = ["DESCRIPCIÓN", "S/N", "DATO ADICIONAL",
        "NOMBRE RESPONSABLE", "FIRMA ELECTRÓNICA"]

# ── Alturas ───────────────────────────────────────────────────────────────────
_HH  = 16    # cabecera sección
_CH  = 12    # cabecera columnas
_IH  = 12    # fila info (datos personales)

# ── Paleta de colores (R, G, B en 0–1) ───────────────────────────────────────
_C_HEAD  = (0.07, 0.17, 0.37)   # azul oscuro
_C_COLS  = (0.18, 0.34, 0.61)   # azul medio
_C_TH    = (0.91, 0.93, 0.97)   # gris-azul claro — celdas th
_C_WHITE = (1.0,  1.0,  1.0)
_C_BLACK = (0.0,  0.0,  0.0)
_C_OK    = (0.08, 0.45, 0.08)   # verde
_C_PEND  = (0.55, 0.55, 0.55)   # gris
_C_BKGOK = (0.90, 0.97, 0.90)   # fondo verde tenue — firmado
_C_SI    = (0.06, 0.55, 0.06)   # verde SI
_C_NO    = (0.75, 0.07, 0.07)   # rojo NO
_C_GRAY  = (0.96, 0.96, 0.96)   # compatibilidad

# ── Funciones auxiliares del PDF ─────────────────────────────────────────────

def _split_text(text: str, max_chars: int) -> list:
    words = str(text or "").split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if len(cand) <= max_chars:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or ["—"]


def _draw_page_header(c, formulario: dict, page_num: int) -> None:
    W = 595.28
    c.setFillColorRGB(*_C_HEAD)
    c.rect(_ML, 814, W - 2 * _ML, 22, fill=1, stroke=0)
    c.setFillColorRGB(*_C_WHITE)
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(_ML + 3, 821, "INAMHI")
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(W / 2, 826, "Instituto Nacional de Meteorología e Hidrología")
    c.setFont("Helvetica", 7)
    c.drawCentredString(W / 2, 818, "FORMULARIO PAZ Y SALVO — LIQUIDACIÓN DE HABERES")
    rx = W - _ML - 98
    c.setFont("Helvetica", 6.5)
    c.drawString(rx, 830, "CÓDIGO:  INAMHI-RH-001")
    c.drawString(rx, 822, "VERSIÓN: 2.0")
    c.drawString(rx, 815, f"PÁGINA:  {page_num + 1}")
    c.setStrokeColorRGB(*_C_HEAD)
    c.setLineWidth(0.5)
    c.line(_ML, 812, W - _ML, 812)
    c.setFillColorRGB(*_C_BLACK)
    c.setStrokeColorRGB(*_C_BLACK)
    c.setLineWidth(0.4)


def _sec_header(c, y: float, num: str, titulo: str) -> float:
    c.setFillColorRGB(*_C_HEAD)
    c.rect(_ML, y - _HH, _CW, _HH, fill=1, stroke=0)
    c.setFillColorRGB(*_C_WHITE)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(_ML + 3, y - _HH + 5, f"{num}.")
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(_ML + 18, y - _HH + 5, titulo.upper())
    c.setFillColorRGB(*_C_BLACK)
    return y - _HH


def _col_header(c, y: float, xs: list, ws: list, labels: list) -> float:
    c.setFillColorRGB(*_C_COLS)
    c.setLineWidth(0.3)
    for x, w in zip(xs, ws):
        c.rect(x, y - _CH, w, _CH, fill=1, stroke=1)
    c.setFillColorRGB(*_C_WHITE)
    c.setFont("Helvetica-Bold", 5.5)
    for lbl, x in zip(labels, xs):
        c.drawString(x + 2, y - _CH + 4, str(lbl))
    c.setFillColorRGB(*_C_BLACK)
    return y - _CH


def _info_row(c, y: float, l1: str, v1: str,
              l2: str = "", v2: str = "", span: bool = False) -> float:
    c.setLineWidth(0.3)
    c.setFillColorRGB(*_C_TH)
    c.rect(30, y - _IH, 86, _IH, fill=1, stroke=1)
    c.setFillColorRGB(*_C_BLACK)
    c.setFont("Helvetica-Bold", 5.8)
    c.drawString(32, y - _IH + 4, str(l1 or "")[:17])
    if span or not l2:
        c.setFillColorRGB(*_C_WHITE)
        c.rect(116, y - _IH, 449, _IH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_BLACK)
        c.setFont("Helvetica", 5.8)
        c.drawString(118, y - _IH + 4, str(v1 or "—")[:95])
    else:
        c.setFillColorRGB(*_C_WHITE)
        c.rect(116, y - _IH, 182, _IH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_BLACK)
        c.setFont("Helvetica", 5.8)
        c.drawString(118, y - _IH + 4, str(v1 or "—")[:30])
        c.setFillColorRGB(*_C_TH)
        c.rect(298, y - _IH, 86, _IH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_BLACK)
        c.setFont("Helvetica-Bold", 5.8)
        c.drawString(300, y - _IH + 4, str(l2 or "")[:17])
        c.setFillColorRGB(*_C_WHITE)
        c.rect(384, y - _IH, 181, _IH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_BLACK)
        c.setFont("Helvetica", 5.8)
        c.drawString(386, y - _IH + 4, str(v2 or "—")[:30])
    return y - _IH


def _draw_firma_cell(c, y: float, firma_val: str,
                     campo: str, sig_coords: dict, page_num: int) -> None:
    y_bot = y - _FRH
    sig_coords[campo] = (int(_FX1), int(y_bot), int(_FX2), int(y), page_num)
    if firma_val and firma_val.startswith("FIRMADO_EC:"):
        c.setFillColorRGB(*_C_BKGOK)
        c.rect(_FX1, y_bot, _FW, _FRH, fill=1, stroke=1)
        if "|" in firma_val:
            b64_raw = firma_val.split("|", 1)[1]
            if b64_raw.startswith("data:image"):
                b64_raw = b64_raw.split(",", 1)[-1]
            try:
                import io as _io2, base64 as _b64_2
                from reportlab.lib.utils import ImageReader
                img_r = ImageReader(_io2.BytesIO(_b64_2.b64decode(b64_raw)))
                pad = 3
                c.drawImage(img_r, _FX1 + pad, y_bot + pad,
                            width=_FW - 2 * pad, height=_FRH - 2 * pad,
                            preserveAspectRatio=True, anchor='c', mask='auto')
                return
            except Exception:
                pass
        parts = firma_val.split("|")[0].split(":")
        firmante = parts[1] if len(parts) > 1 else "Firmado"
        fecha_f  = parts[2][:10] if len(parts) > 2 else ""
        c.setFillColorRGB(*_C_OK)
        c.setFont("Helvetica-Bold", 6)
        c.drawString(_FX1 + 3, y - 13, "FIRMADO ELECTRONICAMENTE")
        c.setFont("Helvetica", 5.5)
        c.setFillColorRGB(*_C_BLACK)
        ty = y - 24
        for ln in _split_text(firmante, 22)[:3]:
            c.drawString(_FX1 + 3, ty, ln)
            ty -= 8
        c.setFillColorRGB(*_C_PEND)
        c.setFont("Helvetica", 5)
        c.drawString(_FX1 + 3, y_bot + 5, fecha_f)
    else:
        c.setFillColorRGB(*_C_WHITE)
        c.rect(_FX1, y_bot, _FW, _FRH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_PEND)
        c.setFont("Helvetica", 5.5)
        c.drawString(_FX1 + 4, y_bot + 5, "[FirmaEC]")
    c.setFillColorRGB(*_C_BLACK)


def _firma_row(c, y: float, xs: list, ws: list, cells: list,
               campo: str, firma_val: str,
               sig_coords: dict, page_num: int) -> float:
    y_bot = y - _FRH
    c.setLineWidth(0.35)
    for i, (txt, bg) in enumerate(cells):
        c.setFillColorRGB(*bg)
        c.rect(xs[i], y_bot, ws[i], _FRH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_BLACK)
        s = str(txt or "")
        if s and not s.startswith("data:") and not s.startswith("FIRMADO_EC:"):
            c.setFont("Helvetica", 6)
            lns = _split_text(s, max(ws[i] // 5, 8))
            ty = y - 10
            for ln in lns[:5]:
                c.drawString(xs[i] + 3, ty, ln)
                ty -= 8
    _draw_firma_cell(c, y, firma_val, campo, sig_coords, page_num)
    return y - _FRH


def _dir_row(c, y: float, texto: str,
             sig_coords: dict, campo: str, firma_val: str, page_num: int) -> float:
    y_bot = y - _FRH
    ancho = _FX1 - _ML
    c.setLineWidth(0.35)
    c.setFillColorRGB(0.95, 0.96, 1.0)
    c.rect(_ML, y_bot, ancho, _FRH, fill=1, stroke=1)
    c.setFillColorRGB(*_C_BLACK)
    c.setFont("Helvetica-Bold", 6.5)
    c.drawString(_ML + 4, y - 13, "Director/a / Responsable:")
    c.setFont("Helvetica", 6)
    ty = y - 23
    for ln in _split_text(texto, 62)[:3]:
        c.drawString(_ML + 4, ty, ln)
        ty -= 9
    _draw_firma_cell(c, y, firma_val, campo, sig_coords, page_num)
    return y - _FRH


# Compatibilidad con código heredado que aún use la estructura anterior
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
    {
        "titulo": "8. AUTORIZACIÓN — SERVIDOR SALIENTE",
        "rows": [
            ("Firma de Autorización del Servidor Saliente (Art. 110 Reglamento LOSEP)",
             "nombres_apellidos", "servidor_saliente"),
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


@app.route("/api/formularios/<int:formulario_id>/pdf", methods=["GET"])
def generar_pdf(formulario_id):
    """
    Genera el PDF Paz y Salvo con diseño idéntico a la hoja espejo del frontend.
    Registra las coordenadas de cada celda FirmaEC en JSON para pyHanko (PAdES).
    Sirve _signed.pdf si existe; si no, el original recién generado.
    """
    conn = cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM formularios WHERE id = %s", (formulario_id,))
        formulario = cursor.fetchone()
        if not formulario:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        if user["rol"] != "Administrador" and formulario["estado"] == "BORRADOR":
            return jsonify({"mensaje": "El formulario aún está en borrador"}), 400

        cursor.execute("""
            SELECT p.codigo, r.respuesta
              FROM formulario_preguntas p
              LEFT JOIN formulario_respuestas r ON p.id = r.pregunta_id
             WHERE p.formulario_id = %s
        """, (formulario_id,))
        resp = {r["codigo"]: (r["respuesta"] or "") for r in cursor.fetchall() if r["codigo"]}

        filename  = f"formulario_{formulario_id}.pdf"
        filepath  = os.path.join(UPLOAD_FOLDER, filename)
        json_path = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_sigfields.json")

        c          = canvas.Canvas(filepath, pagesize=A4)
        W, _H      = A4
        sig_coords = {}
        pg         = 0
        y          = _MT

        _draw_page_header(c, formulario, pg)

        def _npage():
            nonlocal pg, y
            c.showPage(); pg += 1; y = _MT
            _draw_page_header(c, formulario, pg)

        def _need(h: float):
            if y - h < _MB:
                _npage()

        def _v(campo: str) -> str:
            val = resp.get(campo, "")
            if not val or val.startswith("data:") or val.startswith("FIRMADO_EC:"):
                return "—"
            return str(val)

        def _f(campo: str) -> str:
            return resp.get(campo, "")

        def _yb(val: str):
            if val == "SI": return _C_SI
            if val == "NO": return _C_NO
            return _C_WHITE

        # ─── Título ─────────────────────────────────────────────────────────
        _need(30)
        c.setFont("Helvetica-Bold", 12)
        c.setFillColorRGB(*_C_HEAD)
        c.drawCentredString(W / 2, y - 15, "PAZ Y SALVO INSTITUCIONAL")
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(*_C_PEND)
        c.drawCentredString(W / 2, y - 25,
            f"Estado: {formulario.get('estado','—')}  |  Progreso: {formulario.get('porcentaje',0)}%")
        c.setFillColorRGB(*_C_BLACK)
        y -= 32

        # ═══ 01 DATOS PERSONALES ═══════════════════════════════════════════
        _need(_HH + 6 * _IH + 4)
        y = _sec_header(c, y, "01", "DATOS PERSONALES Y LABORALES")
        y = _info_row(c, y, "NOMBRES Y APELLIDOS", _v("nombres_apellidos"), span=True)
        y = _info_row(c, y, "CÉDULA / PASAPORTE",  _v("cedula"),
                             "MODALIDAD LABORAL",   _v("modalidad"))
        y = _info_row(c, y, "FECHA DE INGRESO",     _v("fecha_ingreso"),
                             "FECHA DE SALIDA",      _v("fecha_salida"))
        _dir_val = f"{_v('direccion')} {_v('numero_domicilio')}".strip("— ")
        y = _info_row(c, y, "DIRECCIÓN DOMICILIARIA", _dir_val or "—", span=True)
        y = _info_row(c, y, "PROVINCIA / CANTÓN",
                             f"{_v('provincia')} / {_v('canton')}",
                             "CELULAR / EMERGENCIA",
                             f"{_v('celular')} / {_v('emergencia')}")
        y = _info_row(c, y, "EMAIL PRINCIPAL", _v("email1"),
                             "EMAIL SECUNDARIO", _v("email2"))
        y -= 4

        # ═══ 02 DIRECCIÓN / UNIDAD ══════════════════════════════════════════
        _need(_HH + 3 * _IH + 4)
        y = _sec_header(c, y, "02", "DIRECCIÓN / UNIDAD QUE PRESTÓ SUS SERVICIOS")
        y = _info_row(c, y, "LUGAR DE TRABAJO", _v("lugar_trabajo"),
                             "GRUPO OCUPACIONAL", _v("grupo_ocupacional"))
        y = _info_row(c, y, "DIRECCIÓN / UNIDAD", _v("unidad"), span=True)
        y = _info_row(c, y, "CARGO DESEMPEÑADO",  _v("cargo"),  span=True)
        y -= 4

        # ═══ 03 TRÁMITES — 6 columnas ══════════════════════════════════════
        _need(_HH + _CH + 4 * _FRH + 4)
        y = _sec_header(c, y, "03", "ENTREGA / GESTIÓN DOCUMENTAL Y DE TRÁMITES")
        y = _col_header(c, y, _T6X, _T6W, _T6L)

        for (d1, k1, d2, k2, nk, cam) in [
            ("Informe fin de gestión",          "tramites_informe",
             "QUIPUX bandeja en cero",           "tramites_quipux_cero",
             "tramites_nombre_resp1",             "tramites_r1"),
            ("Fe de presentación",              "tramites_fe_presentacion",
             "Claves de acceso asignadas",       "tramites_claves_asignadas",
             "tramites_nombre_resp2",             "tramites_r2"),
            ("Archivo físico / digital LOSEP",  "tramites_losep",
             "Acta entrega de claves",           "tramites_acta_claves",
             "tramites_nombre_resp3",             "tramites_r3"),
        ]:
            _need(_FRH)
            yn1 = _v(k1); yn2 = _v(k2)
            y = _firma_row(c, y, _T6X, _T6W, [
                (d1, _C_WHITE), (yn1, _yb(yn1)),
                (d2, _C_WHITE), (yn2, _yb(yn2)),
                (_v(nk), _C_WHITE),
            ], cam, _f(cam), sig_coords, pg)

        _need(_FRH)
        jt = (f"Jefe: {_v('tramites_jefe_inmediato')} | "
              f"Recibe: {_v('tramites_servidor_recibe')}")
        y = _firma_row(c, y, _T6X, _T6W, [
            (jt, _C_WHITE), ("", _C_WHITE), ("", _C_WHITE),
            ("", _C_WHITE), (_v("tramites_nombre_responsable"), _C_WHITE),
        ], "tramites_jefe", _f("tramites_jefe"), sig_coords, pg)
        y -= 4

        # ═══ 04 GESTIÓN ADMINISTRATIVA — 5 columnas ═════════════════════════
        _need(_HH + _CH + 5 * _FRH + 4)
        y = _sec_header(c, y, "04", "GESTIÓN ADMINISTRATIVA — DIR. ADMINISTRATIVA FINANCIERA")
        y = _col_header(c, y, _T5X, _T5W, _T5L)

        for (desc, yk, dato, nk, cam) in [
            ("Entrega informe de actividades",    "admin_informe",
             "—",                                  "admin_nombre_resp1", "admin_r1"),
            ("Entrega bienes muebles / equipos",  "admin_bienes",
             f"$ {_v('admin_valor_bienes')}",      "admin_nombre_resp2", "admin_r2"),
            ("Deducibles pendientes",             "admin_deducibles",
             f"$ {_v('admin_deducibles_valor')}",  "admin_nombre_resp3", "admin_r3"),
            ("Pasajes aéreos por justificar",     "admin_pasajes",
             f"$ {_v('admin_pasajes_valor')}",     "admin_nombre_resp4", "admin_r4"),
        ]:
            _need(_FRH)
            yn = _v(yk)
            y = _firma_row(c, y, _T5X, _T5W, [
                (desc, _C_WHITE), (yn, _yb(yn)), (dato, _C_WHITE), (_v(nk), _C_WHITE),
            ], cam, _f(cam), sig_coords, pg)

        _need(_FRH)
        y = _dir_row(c, y, _v("admin_responsable"),
                     sig_coords, "admin_dir", _f("admin_dir"), pg)
        y -= 4

        # ═══ 05 GESTIÓN TIC — 5 columnas ════════════════════════════════════
        _need(_HH + _CH + 5 * _FRH + 4)
        y = _sec_header(c, y, "05",
                        "GESTIÓN DE TECNOLOGÍAS DE LA INFORMACIÓN Y COMUNICACIÓN")
        y = _col_header(c, y, _T5X, _T5W, _T5L)

        for (desc, yk, dato, nk, cam) in [
            ("Verificación equipo / IP / accesos", "tic_verificacion",
             f"IP:{_v('tic_ip_fija')} Lib:{_v('tic_liberacion')}",
             "tic_nombre_resp1", "tic_r1"),
            ("Entrega backup de información",      "tic_backup",
             f"Ruta: {_v('tic_ruta_backup')}",     "tic_nombre_resp2", "tic_r2"),
            ("Retiro control acceso / contraseñas", "tic_retiro_acceso",
             f"Correo:{_v('tic_cierre_correo')} eSIGEF:{_v('tic_esigef')}",
             "tic_nombre_resp3", "tic_r3"),
            ("Entrega tarjeta acceso / cuentas",  "tic_tarjeta_cuentas",
             f"SPRYN:{_v('tic_spryn')} eSByE:{_v('tic_esbye')}",
             "tic_nombre_resp4", "tic_r4"),
        ]:
            _need(_FRH)
            yn = _v(yk)
            y = _firma_row(c, y, _T5X, _T5W, [
                (desc, _C_WHITE), (yn, _yb(yn)), (dato, _C_WHITE), (_v(nk), _C_WHITE),
            ], cam, _f(cam), sig_coords, pg)

        _need(_FRH)
        y = _dir_row(c, y, _v("tic_responsable"),
                     sig_coords, "tic_r5", _f("tic_r5"), pg)
        y -= 4

        # ═══ 06 GESTIÓN FINANCIERA — 5 columnas ══════════════════════════════
        _need(_HH + _CH + 5 * _FRH + 4)
        y = _sec_header(c, y, "06", "GESTIÓN FINANCIERA")
        y = _col_header(c, y, _T5X, _T5W, _T5L)

        for (desc, yk, dato, nk, cam) in [
            ("Saldos contables pendientes",      "fin_saldos",
             f"$ {_v('fin_saldos_valor')} | {_v('fin_saldos_obs')}",
             "fin_nombre_resp1", "fin_r1"),
            ("Anticipo de sueldos pendiente",    "fin_anticipo",
             f"$ {_v('fin_anticipo_valor')}",    "fin_nombre_resp2", "fin_r2"),
            ("Recuperación de valores",          "fin_recuperacion",
             f"$ {_v('fin_recuperacion_valor')}", "fin_nombre_resp3", "fin_r3"),
            ("Devolución muebles / equipos",     "fin_devolucion",
             f"$ {_v('fin_devolucion_valor')}",  "fin_nombre_resp4", "fin_r4"),
        ]:
            _need(_FRH)
            yn = _v(yk)
            y = _firma_row(c, y, _T5X, _T5W, [
                (desc, _C_WHITE), (yn, _yb(yn)), (dato, _C_WHITE), (_v(nk), _C_WHITE),
            ], cam, _f(cam), sig_coords, pg)

        _need(_FRH)
        y = _dir_row(c, y, _v("fin_director"),
                     sig_coords, "fin_dir", _f("fin_dir"), pg)
        y -= 4

        # ═══ 07 SEGURIDAD — 6 columnas ══════════════════════════════════════
        _need(_HH + _CH + 3 * _FRH + 4)
        y = _sec_header(c, y, "07",
                        "SEGURIDAD DE LA INFORMACIÓN — ACUERDO MINISTERIAL 166 (EGSI)")
        y = _col_header(c, y, _T6X, _T6W, _T6L)

        for (d1, k1, d2, k2, nk, cam) in [
            ("Archivos digitales (EGSI)",           "seg_archivos",
             "Entrega copia de actividades",         "seg_entrega_copia",
             "seg_nombre_resp1", "seg_r1"),
            ("Archivos físicos (Archivo Central)",  "seg_archivos_fisicos",
             "Verificación información institucional", "seg_verificacion_info",
             "seg_nombre_resp2", "seg_r2"),
        ]:
            _need(_FRH)
            yn1 = _v(k1); yn2 = _v(k2)
            y = _firma_row(c, y, _T6X, _T6W, [
                (d1, _C_WHITE), (yn1, _yb(yn1)),
                (d2, _C_WHITE), (yn2, _yb(yn2)),
                (_v(nk), _C_WHITE),
            ], cam, _f(cam), sig_coords, pg)

        _need(_FRH)
        y = _dir_row(c, y,
                     f"Oficial: {_v('seg_oficial')} | Resp: {_v('seg_responsable')}",
                     sig_coords, "seg_oficial", _f("seg_oficial"), pg)
        y -= 4

        # ═══ 08 RRHH — 5 columnas ════════════════════════════════════════════
        _need(_HH + _CH + 9 * _FRH + 4)
        y = _sec_header(c, y, "08",
                        "DIRECCIÓN DE ADMINISTRACIÓN DE RECURSOS HUMANOS")
        y = _col_header(c, y, _T5X, _T5W, _T5L)

        for (desc, yk, dato, nk, cam) in [
            ("Capacitación: devengó cursos",         "rrhh_capacitacion",
             "—",                                     "rrhh_resp_capacitacion",  "rrhh_r1"),
            ("Evaluación del Desempeño aplicada",    "rrhh_evaluacion",
             "—",                                     "rrhh_resp_evaluacion",    "rrhh_r2"),
            ("Viajes exterior: devengación",         "rrhh_viajes",
             "—",                                     "rrhh_resp_viajes",        "rrhh_r3"),
            ("SIITH: desvinculación del sistema",   "rrhh_siith",
             "—",                                     "rrhh_resp_siith",         "rrhh_r4"),
            (f"Vacaciones no gozadas: {_v('rrhh_vacaciones')} días", "—",
             f"N° Cert: {_v('rrhh_num_certificado')}", "rrhh_resp_vacaciones",  "rrhh_r5"),
            ("Declaración juramentada de bienes",   "rrhh_juramentada",
             f"N° Decl: {_v('rrhh_num_declaracion')}",  "rrhh_resp_juramentada", "rrhh_r6"),
            ("Credencial institucional",            "rrhh_credencial",
             "—",                                     "rrhh_resp_credencial2",   "rrhh_r7"),
            ("Acta bienes / Copia activ. / Ropa",  "rrhh_entrega_informe_cd",
             "—",                                     "rrhh_resp_acta",          "rrhh_r8"),
        ]:
            _need(_FRH)
            yn = _v(yk) if yk != "—" else "—"
            y = _firma_row(c, y, _T5X, _T5W, [
                (desc, _C_WHITE), (yn, _yb(yn)), (dato, _C_WHITE), (_v(nk), _C_WHITE),
            ], cam, _f(cam), sig_coords, pg)

        _need(_FRH)
        y = _dir_row(c, y, _v("rrhh_director"),
                     sig_coords, "rrhh_dir", _f("rrhh_dir"), pg)
        y -= 4

        # ═══ 09 RECEPCIÓN ═════════════════════════════════════════════════════
        _need(_HH + 2 * _IH + _FRH + 4)
        y = _sec_header(c, y, "09", "RECEPCIÓN DE DOCUMENTOS — DIRECCIÓN DE RRHH")
        y = _info_row(c, y, "FECHA ENTREGA",         _v("recepcion_fecha"),
                             "N° HOJAS",              _v("recepcion_hojas"))
        y = _info_row(c, y, "SERVIDOR/A QUE RECIBE", _v("recepcion_servidor"),
                             "CARGO",                 _v("recepcion_cargo"))
        _need(_FRH)
        y = _firma_row(c, y, _T5X, _T5W, [
            ("Servidor/a que recibe el Paz y Salvo — RRHH", _C_WHITE),
            ("—", _C_WHITE), ("—", _C_WHITE), ("—", _C_WHITE),
        ], "recepcion_r1", _f("recepcion_r1"), sig_coords, pg)
        y -= 4

        # ═══ 10 AUTORIZACIÓN — SERVIDOR SALIENTE ══════════════════════════════
        _LH = 68
        _need(_HH + _LH + _FRH + 8)
        y = _sec_header(c, y, "10",
                        "AUTORIZACIÓN — SERVIDOR SALIENTE (ART. 110 REGLAMENTO LOSEP)")
        legal = (
            "Conforme lo establecido en el artículo 110 del Reglamento a la Ley Orgánica de "
            "Servicio Público (LOSEP), quien suscribe el presente formulario PAZ Y SALVO "
            "AUTORIZA a la DIRECCIÓN ADMINISTRATIVA FINANCIERA del INAMHI para que efectúe "
            "los descuentos detallados en este documento por reintegro y/o recuperación de "
            "valores, bienes y/o especies encontrados a su cargo, los cuales serán "
            "DESCONTADOS a través del rol de pagos y/o liquidación de haberes."
        )
        c.setFillColorRGB(0.97, 0.97, 1.0)
        c.rect(_ML, y - _LH, _CW, _LH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_BLACK)
        c.setFont("Helvetica", 6.5)
        ly = y - 10
        for ln in _split_text(legal, 106)[:7]:
            c.drawString(_ML + 6, ly, ln)
            ly -= 9
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(_ML + 6, ly - 2,
                     f"C.C. FIRMANTE: {_v('cedula_firmante')}   "
                     f"FECHA DE FIRMA: {_v('fecha_firma')}")
        y -= _LH + 4
        _need(_FRH)
        y = _dir_row(c, y, "FIRMA DEL SERVIDOR SALIENTE — AUTORIZACIÓN",
                     sig_coords, "servidor_saliente", _f("servidor_saliente"), pg)

        # Pie de página
        c.setFillColorRGB(*_C_PEND)
        c.setFont("Helvetica", 5.5)
        c.drawCentredString(W / 2, _MB - 8,
            "INAMHI — Formulario Paz y Salvo — Liquidación de Haberes — Versión 2.0 — Quito, Ecuador")
        c.setFillColorRGB(*_C_BLACK)

        c.save()
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(sig_coords, jf)

        # Servir _signed.pdf (pyHanko) si existe, si no el original
        pdf_signed = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_signed.pdf")
        if os.path.exists(pdf_signed):
            return send_from_directory(
                UPLOAD_FOLDER,
                f"formulario_{formulario_id}_signed.pdf",
                as_attachment=True,
                download_name=f"PazSalvo_{formulario_id}_firmado.pdf",
            )
        return send_from_directory(
            UPLOAD_FOLDER, filename, as_attachment=True,
            download_name=f"PazSalvo_{formulario_id}.pdf"
        )

    except Exception as e:
        return jsonify({"mensaje": "Error al generar PDF",
                        "error": str(e), "detalle": traceback.format_exc()}), 500
    finally:
        close_db(cursor, conn)


# ═══════════════════════════════════════════════════════════════
#  ENDPOINT: PDF FIRMADO POR FIRMAEC DESKTOP (AutoFirma)
# ═══════════════════════════════════════════════════════════════

@app.route("/api/formularios/<int:formulario_id>/firmar-ec-desktop", methods=["POST"])
def firmar_ec_desktop(formulario_id):
    """
    Recibe un PDF ya firmado externamente por FirmaEC Desktop (AutoFirma).

    Valida que el PDF contenga al menos una firma digital PAdES,
    extrae el nombre del firmante del certificado incrustado,
    guarda el PDF como la versión firmada del formulario y registra
    el campo en la BD con el mismo flujo que firmar_ec_pdf.

    Form-data esperado:
        campo_firma      : str  – clave de la celda (ej: 'tic_r1')
        pdf_firmado_b64  : str  – PDF firmado codificado en base64
        cert_b64         : str  – (opcional) certificado del firmante en base64
    """
    import base64 as _b64
    conn = cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        campo_firma     = (request.form.get("campo_firma") or "").strip()
        pdf_b64         = (request.form.get("pdf_firmado_b64") or "").strip()
        cert_b64        = (request.form.get("cert_b64") or "").strip()

        if not campo_firma:
            return jsonify({"mensaje": "campo_firma es requerido"}), 400
        if not pdf_b64:
            return jsonify({"mensaje": "pdf_firmado_b64 es requerido"}), 400

        # ── Decodificar PDF ──────────────────────────────────────
        try:
            pdf_bytes = _b64.b64decode(pdf_b64)
        except Exception:
            return jsonify({"mensaje": "El PDF firmado tiene codificación base64 inválida"}), 400

        if len(pdf_bytes) < 5 or pdf_bytes[:5] != b'%PDF-':
            return jsonify({"mensaje": "El archivo recibido no es un PDF válido"}), 400

        # ── Validar firma digital incrustada ─────────────────────
        # FirmaEC Desktop 5.x usa PAdES/PKCS#7. pyHanko puede no reconocerlo
        # dependiendo de la versión; por eso validamos con múltiples métodos.
        signer_name      = None
        firma_encontrada = False

        # Método 1: pyHanko embedded_signatures
        try:
            import io as _io
            from pyhanko.pdf_utils.reader import PdfFileReader as _PdfR
            _reader = _PdfR(_io.BytesIO(pdf_bytes))
            _sigs   = list(_reader.embedded_signatures)

            if _sigs:
                firma_encontrada = True
                try:
                    from asn1crypto import x509 as _x509
                    _raw = _sigs[-1].signer_cert.dump()
                    _c   = _x509.Certificate.load(_raw)
                    signer_name = _c.subject.human_friendly
                except Exception:
                    pass
                if not signer_name:
                    try:
                        signer_name = _sigs[-1].sig_object.get('/Name', '').strip() or None
                    except Exception:
                        pass
        except ImportError:
            pass
        except Exception as _ve:
            print(f"[firmar-ec-desktop] pyhanko check: {_ve}")

        # Método 2: inspección raw del PDF (FirmaEC usa /Sig con /ByteRange + /Contents)
        if not firma_encontrada:
            _scan = pdf_bytes[:300_000]
            _hard = [b'/ByteRange', b'adbe.pkcs7', b'ETSI.CAdES', b'ETSI.RFC3161',
                     b'pkcs7-detached', b'pkcs7.sha1', b'ETSI.CAdES.detached']
            _soft = [b'/Sig', b'/SubFilter', b'/Contents', b'/Filter', b'Adobe.PPKLite']
            _hard_found = sum(1 for i in _hard if i in _scan)
            _soft_found = sum(1 for i in _soft if i in _scan)
            # Firma válida si hay al menos 1 indicador fuerte O 3 débiles
            if _hard_found >= 1 or _soft_found >= 3:
                firma_encontrada = True
                print(f"[firmar-ec-desktop] Firma detectada raw: hard={_hard_found} soft={_soft_found}")

        if not firma_encontrada:
            return jsonify({
                "mensaje": (
                    "El PDF no contiene una firma digital reconocida. "
                    "Pasos para firmar correctamente:\n"
                    "1. Abra FirmaEC 5.1 → pestaña 'Firmar Documento (1)'.\n"
                    "2. Cargue el PDF descargado (el original, no una copia).\n"
                    "3. Seleccione su certificado .p12 y contraseña.\n"
                    "4. Haga clic en 'Firmar' y espere que FirmaEC genere el PDF firmado.\n"
                    "5. El PDF FIRMADO (no el original) es el que debe subir aquí."
                )
            }), 400

        # Si no se pudo extraer del PDF, intentar con cert_b64 provisto por el cliente
        if not signer_name and cert_b64:
            try:
                from cryptography import x509 as _x509_crypto
                from cryptography.hazmat.primitives.serialization import Encoding
                cert_der = _b64.b64decode(cert_b64)
                cert_obj_c = _x509_crypto.load_der_x509_certificate(cert_der)
                cn_attrs = cert_obj_c.subject.get_attributes_for_oid(
                    _x509_crypto.NameOID.COMMON_NAME
                )
                signer_name = cn_attrs[0].value.upper() if cn_attrs else None
            except Exception:
                pass

        signer_name = signer_name or user.get("usuario", "FIRMANTE").upper()

        # ── Consultas BD ─────────────────────────────────────────
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id FROM formularios WHERE id = %s", (formulario_id,))
        if not cursor.fetchone():
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        cursor.execute("""
            SELECT p.id AS pregunta_id,
                   a.id AS asignacion_id,
                   a.asignado_usuario_id
            FROM   formulario_preguntas p
            INNER  JOIN formulario_asignaciones a ON p.id = a.pregunta_id
            WHERE  p.formulario_id = %s AND p.codigo = %s
            LIMIT  1
        """, (formulario_id, campo_firma))
        fila = cursor.fetchone()

        if not fila:
            return jsonify({"mensaje": f"La celda '{campo_firma}' no existe en este formulario"}), 404

        if user["rol"] != "Administrador" and fila["asignado_usuario_id"] != user["id"]:
            return jsonify({"mensaje": "No tiene autorización para firmar esta celda."}), 403

        cursor.execute("""
            SELECT id FROM formulario_respuestas
            WHERE  formulario_id = %s AND pregunta_id = %s LIMIT 1
        """, (formulario_id, fila["pregunta_id"]))
        if cursor.fetchone():
            return jsonify({"mensaje": "Esta celda ya fue firmada y no puede modificarse."}), 400

        # ── Guardar PDF firmado por FirmaEC Desktop ───────────────
        # Se guarda en _firmaec.pdf (separado de _signed.pdf de pyHanko)
        # para que generar_pdf pueda servirlo y FirmaEC pueda verificarlo.
        pdf_firmaec = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_firmaec.pdf")
        with open(pdf_firmaec, "wb") as fout:
            fout.write(pdf_bytes)

        # ── Registrar en BD ──────────────────────────────────────
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

        cursor.execute("""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN estado = 'CULMINADO' THEN 1 ELSE 0 END) AS completados
              FROM formulario_asignaciones WHERE formulario_id = %s
        """, (formulario_id,))
        prog        = cursor.fetchone()
        total_asig  = prog["total"] or 0
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
            "Firma digital EC Desktop",
            f"Firmó celda '{campo_firma}' en formulario {formulario_id} como '{signer_name}'"
        )

        return jsonify({
            "mensaje":    "PDF firmado y validado correctamente con FirmaEC Desktop.",
            "firmado_por": signer_name,
            "porcentaje":  porcentaje,
            "estado":      estado_form,
        }), 200

    except Exception as e:
        if conn:
            conn.rollback()
        print("[ERROR /firmar-ec-desktop]", traceback.format_exc())
        return jsonify({"mensaje": "Error al procesar firma", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)


# ═══════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════
#  ENDPOINT: SELLO PREVIEW QR (sin autenticación, para img src)
# ═══════════════════════════════════════════════════════════════

@app.route("/api/sello-preview", methods=["GET"])
def sello_preview():
    """
    Devuelve imagen PNG del sello FirmaEC (QR + texto) para un firmante dado.
    No requiere autenticación — se usa como src de img en la hoja espejo.
    Parámetros: ?nombre=NOMBRE%20APELLIDO
    """
    from flask import make_response
    nombre = (request.args.get("nombre") or "FIRMANTE").strip()
    try:
        import base64 as _b64mod
        b64_data_url = _generar_sello_preview(nombre)
        png_bytes = _b64mod.b64decode(b64_data_url.split(",")[1])
        resp = make_response(png_bytes)
        resp.headers["Content-Type"]  = "image/png"
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════
#  ENDPOINT: PDF ORIGINAL COMO BYTES (para FirmaEC Desktop)
# ═══════════════════════════════════════════════════════════════

@app.route("/api/formularios/<int:formulario_id>/pdf-bytes", methods=["GET"])
def obtener_pdf_bytes(formulario_id):
    """
    Devuelve el PDF del formulario como bytes (application/pdf) con soporte
    para Authorization header — usado por el flujo FirmaEC Desktop.
    """
    conn = cursor = None
    try:
        user, error = validar_login()
        if error:
            return error

        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM formularios WHERE id = %s", (formulario_id,))
        if not cursor.fetchone():
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        pdf_signed = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_signed.pdf")
        pdf_orig   = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}.pdf")

        # Si el PDF no existe aún, generarlo en el momento
        if not os.path.exists(pdf_signed) and not os.path.exists(pdf_orig):
            close_db(cursor, conn)
            cursor = conn = None
            gen_resp = generar_pdf(formulario_id)
            # generar_pdf devuelve una Response; si es error no hay archivo
            if hasattr(gen_resp, 'status_code') and gen_resp.status_code not in (200,):
                return jsonify({"mensaje": "No se pudo generar el PDF automáticamente."}), 500

        # Para el flujo FirmaEC Desktop:
        # - Si ya existe _firmaec.pdf (alguien firmó con FirmaEC antes), servir ESE
        #   para que FirmaEC pueda agregar su firma INCREMENTAL sobre las anteriores.
        # - Si no, servir el original limpio.
        # NUNCA servir _signed.pdf (pyHanko) porque FirmaEC no puede firmar encima.
        pdf_firmaec = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_firmaec.pdf")
        if os.path.exists(pdf_firmaec):
            ruta = pdf_firmaec
        elif os.path.exists(pdf_orig):
            ruta = pdf_orig
        else:
            return jsonify({"mensaje": "No se pudo crear el PDF."}), 500

        from flask import send_file as _send_file
        return _send_file(ruta, mimetype="application/pdf", as_attachment=False)

    except Exception as e:
        return jsonify({"mensaje": "Error al obtener PDF", "error": str(e)}), 500
    finally:
        close_db(cursor, conn)

#nuevo 

@app.route("/api/formularios/<int:formulario_id>/pdf-final", methods=["GET"])
def descargar_pdf_final(formulario_id):
    user, error = validar_login()
    if error:
        return error

    pdf_signed = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_signed.pdf")
    pdf_orig   = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}.pdf")

    if os.path.exists(pdf_signed):
        return send_from_directory(
            UPLOAD_FOLDER,
            f"formulario_{formulario_id}_signed.pdf",
            as_attachment=False,
            download_name=f"PazSalvo_{formulario_id}_firmado.pdf",
            mimetype="application/pdf"
        )

    if os.path.exists(pdf_orig):
        return send_from_directory(
            UPLOAD_FOLDER,
            f"formulario_{formulario_id}.pdf",
            as_attachment=False,
            download_name=f"PazSalvo_{formulario_id}.pdf",
            mimetype="application/pdf"
        )

    generar_pdf(formulario_id)

    if os.path.exists(pdf_orig):
        return send_from_directory(
            UPLOAD_FOLDER,
            f"formulario_{formulario_id}.pdf",
            as_attachment=False,
            download_name=f"PazSalvo_{formulario_id}.pdf",
            mimetype="application/pdf"
        )

    return jsonify({"mensaje": "No se pudo generar el PDF final"}), 500


# ═══════════════════════════════════════════════════════════════
#  FIRMA DIGITAL EC  (pyHanko + PAdES)
# ═══════════════════════════════════════════════════════════════

# ── Helpers para carga de certificados FirmaEC Ecuador ──────────────────────

def _encontrar_openssl_git() -> str:
    """
    Localiza openssl.exe de Git for Windows.
    Git for Windows incluye OpenSSL 3.x con el proveedor legacy (RC2/3DES)
    correctamente configurado, a diferencia del OpenSSL que bundlea Python.
    """
    import shutil as _sh
    for _c in [
        r'C:\Program Files\Git\mingw64\bin\openssl.exe',
        r'C:\Program Files (x86)\Git\mingw64\bin\openssl.exe',
        r'C:\Program Files\Git\usr\bin\openssl.exe',
        r'C:\Git\mingw64\bin\openssl.exe',
    ]:
        if os.path.isfile(_c):
            return _c
    return _sh.which('openssl') or ''


def _separar_primer_cert_pem(combined_path: str, out_path: str) -> bool:
    """
    Extrae solo el primer bloque BEGIN CERTIFICATE del PEM combinado
    (cert del firmante).  El resto son CAs intermedias/raíz.
    """
    with open(combined_path, 'r', encoding='utf-8', errors='replace') as _f:
        _txt = _f.read()
    _blocks = re.findall(
        r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',
        _txt, re.DOTALL
    )
    if not _blocks:
        return False
    with open(out_path, 'w', encoding='utf-8') as _f:
        _f.write(_blocks[0] + '\n')
    return True


def _cargar_signer_firmaec(p12_bytes: bytes, password_raw: str):
    """
    Carga un PKCS#12 de FirmaEC Ecuador en un SimpleSigner de pyHanko.
    Soporta algoritmos legacy RC2/3DES (ANF, Security Data, BCE, eCOM).

    Estrategia:
      1. SimpleSigner.load_pkcs12 directo — funciona si oscrypto tiene acceso
         al proveedor OpenSSL legacy (Linux/macOS o Windows con config correcta).
      2. Extraer clave+cert a PEM NO cifrado via openssl.exe de Git for Windows
         (que SÍ tiene RC2/3DES), luego cargar con SimpleSigner.load() que no
         pasa por el CNG de Windows (que no soporta RC2).

    Returns: (signer_obj, error_o_None)
    """
    import tempfile as _tm2
    import subprocess as _sub2
    from pyhanko.sign import signers as _ph2

    # ── Intento 1: load_pkcs12 directo ─────────────────────────────────────
    _tmp1 = None
    try:
        with _tm2.NamedTemporaryFile(suffix='.p12', delete=False) as _f:
            _f.write(p12_bytes)
            _tmp1 = _f.name
        return _ph2.SimpleSigner.load_pkcs12(
            pfx_file=_tmp1,
            passphrase=password_raw.encode('utf-8'),
        ), None
    except Exception as _e1:
        _last = _e1
    finally:
        if _tmp1 and os.path.exists(_tmp1):
            try:
                os.unlink(_tmp1)
            except Exception:
                pass

    # ── Intento 2: openssl de Git → PEM sin cifrar → SimpleSigner.load ─────
    # Root cause: oscrypto usa Windows CNG que NO soporta RC2 (cifrado del
    # contenedor PKCS#12 de los certificados ecuatorianos). La solución es
    # extraer la clave privada a PEM no cifrado usando el openssl.exe de Git
    # (que sí tiene el proveedor legacy) y cargar el PEM con SimpleSigner.load()
    # que usa oscrypto solo para el formato de clave, no para el contenedor P12.
    _ossl = _encontrar_openssl_git()
    if not _ossl:
        return None, Exception(
            "Git for Windows no encontrado. Instálelo desde https://git-scm.com "
            "para poder usar certificados FirmaEC en Windows."
        )

    _p12t = _keyt = _certt = _sct = None
    try:
        with _tm2.NamedTemporaryFile(suffix='.p12', delete=False) as _f:
            _f.write(p12_bytes)
            _p12t = _f.name

        _fd, _keyt  = _tm2.mkstemp(suffix='_key.pem')
        os.close(_fd)
        _fd, _certt = _tm2.mkstemp(suffix='_certs.pem')
        os.close(_fd)
        _fd, _sct   = _tm2.mkstemp(suffix='_sc.pem')
        os.close(_fd)

        # Extraer clave privada sin cifrado (-nodes = no DES/encrypt)
        _rk = _sub2.run([
            _ossl, 'pkcs12', '-legacy', '-nocerts', '-nodes',
            '-in',     _p12t,
            '-passin', f'pass:{password_raw}',
            '-out',    _keyt,
        ], capture_output=True, timeout=25)

        # Extraer solo certificados (sin clave privada)
        _rc = _sub2.run([
            _ossl, 'pkcs12', '-legacy', '-nokeys',
            '-in',      _p12t,
            '-passin',  f'pass:{password_raw}',
            '-out',     _certt,
            '-passout', 'pass:',
        ], capture_output=True, timeout=25)

        if _rk.returncode != 0 or _rc.returncode != 0:
            _ek  = _rk.stderr.decode('utf-8', errors='replace')[:400]
            _ec2 = _rc.stderr.decode('utf-8', errors='replace')[:400]
            return None, Exception(
                f"openssl pkcs12 falló (key_rc={_rk.returncode}, "
                f"cert_rc={_rc.returncode}). "
                f"key_stderr: {_ek} | cert_stderr: {_ec2}"
            )

        if os.path.getsize(_keyt) == 0 or os.path.getsize(_certt) == 0:
            return None, Exception("openssl extrajo archivos vacíos del .p12 — contraseña incorrecta")

        # Primer cert del PEM combinado = certificado del firmante
        _cert_para_cargar = _certt
        if _separar_primer_cert_pem(_certt, _sct):
            _cert_para_cargar = _sct

        signer = _ph2.SimpleSigner.load(
            key_file=_keyt,
            cert_file=_cert_para_cargar,
        )
        return signer, None

    except Exception as _e2:
        return None, _e2
    finally:
        for _p in [_p12t, _keyt, _certt, _sct]:
            if _p and os.path.exists(_p):
                try:
                    os.unlink(_p)
                except Exception:
                    pass


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

        # ── Cargar y validar el certificado directamente con pyHanko ──
        # Los certificados FirmaEC Ecuador (ANF, Security Data, BCE, etc.) usan
        # algoritmos legacy (RC2/3DES) que OpenSSL 3.x rechaza. pyHanko tiene
        # mejor compatibilidad con estos formatos al usar oscrypto internamente.
        # ── Cargar certificado .p12 (FirmaEC Ecuador — soporta RC2/3DES legacy) ──
        # Root cause del problema en Windows: oscrypto usa el CNG del sistema que
        # NO soporta RC2/3DES.  _cargar_signer_firmaec() resuelve esto extrayendo
        # la clave a PEM via openssl.exe de Git for Windows y luego cargando el PEM
        # con SimpleSigner.load() que no involucra el CNG para el contenedor P12.
        import importlib as _ilib
        if _ilib.util.find_spec('pyhanko') is None:
            return jsonify({"mensaje": "pyHanko no está instalado en el servidor"}), 500

        _signer_obj, _load_err = _cargar_signer_firmaec(p12_bytes, password_raw)

        if _signer_obj is None:
            _err_msg = str(_load_err) if _load_err else "Error desconocido"
            print(f"[firmar-ec] No se pudo cargar el .p12 '{p12_file.filename}': {_err_msg}")
            return jsonify({
                "mensaje": (
                    "No se pudo cargar el certificado. Verifique:\n"
                    "• Contraseña incorrecta\n"
                    "• Certificado expirado o revocado\n"
                    "• En Windows se requiere Git for Windows (https://git-scm.com)\n"
                    "• Pruebe exportar el .p12 nuevamente desde la aplicación FirmaEC"
                )
            }), 400

        # ── Nombre del firmante desde el CN del certificado ─────────────────
        signer_name = None
        try:
            _subj_str = _signer_obj.signing_cert.subject.human_friendly
            signer_name = (
                _subj_str.split("Common Name:")[1].split(",")[0].strip().upper()
                if "Common Name:" in _subj_str
                else _subj_str.split("=")[-1].strip().upper()
            )
        except Exception:
            pass
        if not signer_name:
            signer_name = user.get("usuario", "FIRMANTE").upper()

        # _signer_obj listo — se pasa directamente a _pyhanko_firmar

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
            # Generar el PDF automáticamente si no existe
            try:
                close_db(cursor, conn)
                cursor = conn = None
                _gen = generar_pdf(formulario_id)
                if hasattr(_gen, 'status_code') and _gen.status_code not in (200,):
                    return jsonify({"mensaje": "No se pudo generar el PDF automáticamente."}), 500
                conn    = get_connection()
                cursor  = conn.cursor(dictionary=True)
            except Exception as _eg:
                return jsonify({"mensaje": f"No se pudo generar el PDF: {_eg}"}), 500
            pdf_src = pdf_signed if os.path.exists(pdf_signed) else pdf_orig

        if not os.path.exists(pdf_src):
            return jsonify({
                "mensaje": "El PDF no se pudo generar. Use 'Descargar PDF' primero."
            }), 400

        # Si no existe el JSON o al campo le faltan coordenadas → regenerar PDF
        _json_ok = os.path.exists(json_path)
        _campo_falta = False
        if _json_ok:
            try:
                with open(json_path, "r", encoding="utf-8") as _jf_chk:
                    _map_chk = json.load(_jf_chk)
                if campo_firma not in _map_chk:
                    _campo_falta = True
            except Exception:
                _json_ok = False

        if not _json_ok or _campo_falta:
            # Auto-regenerar PDF para actualizar coordenadas
            try:
                close_db(cursor, conn)
                cursor = conn = None
                generar_pdf(formulario_id)
                conn   = get_connection()
                cursor = conn.cursor(dictionary=True)
            except Exception:
                if not _json_ok:
                    return jsonify({
                        "mensaje": "El mapa de coordenadas no existe. Use 'Descargar PDF' primero."
                    }), 400

        # ── Firmar con pyHanko ───────────────────────────────────
        # Destino siempre es _signed.pdf (se sobreescribe incrementalmente)
        pdf_firmado = pdf_signed
        try:
            _pyhanko_firmar(
                src_path    = pdf_src,
                dst_path    = pdf_firmado,
                p12_bytes   = p12_bytes,
                password    = password_raw,
                signer_name = signer_name,
                campo_firma = campo_firma,
                json_path   = json_path,
                signer_obj  = _signer_obj,   # ya cargado — evita re-leer el .p12
            )
        except RuntimeError as exc:
            return jsonify({"mensaje": str(exc)}), 400

        # ── Guardar resultado en BD ──────────────────────────────
        # Formato: FIRMADO_EC:{nombre}:{fecha}|{base64_png}
        # generar_pdf lee la parte antes del "|"; el frontend usa el base64 para mostrar QR.
        fecha_firma = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            _sello_b64 = _generar_sello_preview(signer_name)
        except Exception:
            _sello_b64 = ""
        marca = f"FIRMADO_EC:{signer_name}:{fecha_firma}|{_sello_b64}"
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

        # Recalcular porcentaje usando el total fijo de campos del espejo
        TOTAL_CAMPOS_ESPEJO = 147
        cursor.execute("""
            SELECT COUNT(*) AS completados
              FROM formulario_asignaciones
             WHERE formulario_id = %s AND estado = 'CULMINADO'
        """, (formulario_id,))
        prog        = cursor.fetchone()
        completados = prog["completados"] or 0
        porcentaje  = min(round((completados / TOTAL_CAMPOS_ESPEJO) * 100), 100)
        estado_form = "COMPLETADO" if completados >= TOTAL_CAMPOS_ESPEJO else "EN_PROCESO"

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
            "mensaje"     : "PDF firmado correctamente con su certificado FirmaEC.",
            "firmado_por" : signer_name,
            "porcentaje"  : porcentaje,
            "estado"      : estado_form,
            "firma_imagen": _sello_b64,
        }), 200

    except Exception as exc:
        if conn:
            conn.rollback()
        return jsonify({"mensaje": "Error inesperado al firmar", "error": str(exc)}), 500
    finally:
        close_db(cursor, conn)


def _generar_sello_preview(signer_name: str) -> str:
    """
    Genera PNG del sello FirmaEC — fiel copia del formato oficial.

    Layout (idéntico al sello que imprime FirmaEC Ecuador):
    ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
    │  [QR grande]  │  Validar únicamente en FirmaEC.         │
    │               │  Firmado electrónicamente por:          │
    │               │  NOMBRE FIRMANTE (negrita grande)        │
    └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
    """
    import qrcode as _qrc
    from PIL import Image as _Img, ImageDraw as _Drw, ImageFont as _Font
    import io as _io2, base64 as _b64, unicodedata as _ud

    # Normalizar a NFC para evitar bugs de PIL con chars compuestos (é, ó, ú…)
    def _nfc(s):
        return _ud.normalize('NFC', s)

    # ── Dimensiones (super-sampling x3 → downscale final con LANCZOS) ─
    SCALE  = 3
    IMG_W  = 660 * SCALE   # un poco más ancho para dar espacio al texto
    IMG_H  = 200 * SCALE   # un poco más alto para el nombre largo
    PAD    = 8  * SCALE
    QR_SZ  = IMG_H - PAD * 2
    DIV_X  = PAD + QR_SZ + 10 * SCALE
    TX     = DIV_X + 10 * SCALE
    TW     = IMG_W - TX - PAD

    img  = _Img.new("RGB", (IMG_W, IMG_H), "white")
    draw = _Drw.Draw(img)

    # ── QR Code — ERROR_CORRECT_H para máxima legibilidad ────────
    # Generamos el QR a un tamaño fijo grande y escalamos al área disponible
    qr = _qrc.QRCode(
        version          = None,
        box_size         = 15,            # módulos grandes = QR más fácil de escanear
        border           = 2,
        error_correction = _qrc.constants.ERROR_CORRECT_H,
    )
    qr.add_data("https://validar.firmaec.ec")
    qr.make(fit=True)
    # Usar colores puros para máximo contraste negro/blanco
    qr_pil   = qr.make_image(fill_color=(0, 0, 0), back_color=(255, 255, 255))
    qr_rgb   = qr_pil.convert("RGB")
    # NEAREST preserve los módulos nítidos — sin antialiasing/blur
    qr_final = qr_rgb.resize((QR_SZ, QR_SZ), _Img.NEAREST)
    img.paste(qr_final, (PAD, PAD))

    # ── Divisor vertical ───────────────────────────────────────
    draw.line([(DIV_X, PAD + 4 * SCALE), (DIV_X, IMG_H - PAD - 4 * SCALE)],
              fill=(180, 180, 180), width=SCALE)

    # ── Cargar fuentes TTF con fallback ────────────────────────
    SZ_LABEL = 14 * SCALE   # aumentado para mejor legibilidad
    SZ_SUB   = 13 * SCALE
    SZ_NAME  = 18 * SCALE   # nombre más grande

    _REG = [
        "C:/Windows/Fonts/arial.ttf",    "C:/Windows/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    _BLD = [
        "C:/Windows/Fonts/arialbd.ttf",  "C:/Windows/Fonts/ArialBD.ttf",
        "C:/Windows/Fonts/cour.ttf",     "C:/Windows/Fonts/Cour.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    _MONO = [
        "C:/Windows/Fonts/courbd.ttf",   "C:/Windows/Fonts/CourBD.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    ]

    def _tf(paths, sz):
        for p in paths:
            try:
                return _Font.truetype(p, sz)
            except Exception:
                pass
        try:
            return _Font.load_default(size=sz)
        except Exception:
            return _Font.load_default()

    f_label = _tf(_REG,  SZ_LABEL)
    f_sub   = _tf(_REG,  SZ_SUB)
    f_name  = _tf(_MONO, SZ_NAME)   # Courier Bold — idéntico al sello FirmaEC real

    # ── Dibujar texto — NFC para evitar bugs PIL con acentos ──────
    # Dibujamos palabra por palabra midiendo con textbbox para evitar
    # el bug de PIL donde los acentos distorsionan el avance del cursor.
    def _draw_words(text, x_start, y, font, color):
        words = _nfc(text).split(' ')
        x = x_start
        SPACE_W = max(SZ_LABEL // 4, 4)
        try:
            # Medir el espacio con el font actual
            bb_sp = draw.textbbox((0, 0), 'n n', font=font)
            bb_n  = draw.textbbox((0, 0), 'nn',  font=font)
            SPACE_W = max(bb_sp[2] - bb_n[2], SZ_LABEL // 5)
        except Exception:
            pass
        for w in words:
            if not w:
                continue
            draw.text((x, y), w, font=font, fill=color)
            try:
                bb = draw.textbbox((0, 0), w, font=font)
                x += bb[2] + SPACE_W
            except Exception:
                x += len(w) * (SZ_LABEL // 2) + SPACE_W

    Y1 = PAD + 12 * SCALE
    # Negro puro para máximo contraste — fácil de leer en cualquier impresión
    _draw_words("Validar únicamente en FirmaEC.", TX, Y1, f_label, (0, 0, 0))

    Y2 = Y1 + 20 * SCALE
    _draw_words("Firmado electrónicamente por:", TX, Y2, f_sub, (30, 30, 30))

    # ── Nombre en MAYÚSCULAS — Courier Bold, dividido en líneas ──
    nombre_up = _nfc((signer_name or "FIRMANTE").upper())
    words_n, lines_n, cur_n = nombre_up.split(), [], ""
    for w in words_n:
        test = (cur_n + " " + w).strip() if cur_n else w
        try:
            bb = draw.textbbox((0, 0), test, font=f_name)
            fits = bb[2] <= TW
        except Exception:
            fits = len(test) <= 20
        if fits:
            cur_n = test
        else:
            if cur_n:
                lines_n.append(cur_n)
            cur_n = w
    if cur_n:
        lines_n.append(cur_n)

    ny = Y2 + 22 * SCALE
    for ln in lines_n[:3]:
        draw.text((TX, ny), ln, font=f_name, fill=(0, 0, 0))
        ny += 22 * SCALE

    # ── Borde PUNTEADO (estilo FirmaEC auténtico) ──────────────
    DASH = 8 * SCALE
    GAP  = 5 * SCALE
    BC   = (90, 150, 90)
    BW   = 2 * SCALE
    x1, y1, x2, y2 = 2, 2, IMG_W - 3, IMG_H - 3

    def _dline(p1, p2, horiz):
        if horiz:
            x, ex = p1[0], p2[0]
            while x < ex:
                draw.line([(x, p1[1]), (min(x + DASH, ex), p1[1])], fill=BC, width=BW)
                x += DASH + GAP
        else:
            y, ey = p1[1], p2[1]
            while y < ey:
                draw.line([(p1[0], y), (p1[0], min(y + DASH, ey))], fill=BC, width=BW)
                y += DASH + GAP

    _dline((x1, y1), (x2, y1), True)
    _dline((x1, y2), (x2, y2), True)
    _dline((x1, y1), (x1, y2), False)
    _dline((x2, y1), (x2, y2), False)

    # ── Reducir al tamaño final (anti-aliasing por downscale) ──
    final = img.resize((IMG_W // SCALE, IMG_H // SCALE), _Img.LANCZOS)

    buf = _io2.BytesIO()
    final.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()


def _pyhanko_firmar(
    src_path: str,
    dst_path: str,
    p12_bytes: bytes,
    password: str,
    signer_name: str,
    campo_firma: str,
    json_path: str,
    signer_obj=None,          # objeto SimpleSigner ya cargado (evita releer el .p12)
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

    try:
        from pyhanko.sign import signers, fields as sign_fields
        from pyhanko.sign.signers.pdf_signer import PdfSigner, PdfSignatureMetadata
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.stamp import QRStampStyle
        from pyhanko.stamp.text import TextBoxStyle
    except ImportError:
        raise RuntimeError("pip install pyhanko pyhanko-certvalidator")

    # ── Cargar firmante desde PKCS#12 ────────────────────────────
    if signer_obj is not None:
        signer = signer_obj
    else:
        import tempfile as _tf2
        signer = None
        _encs  = ['utf-8', 'latin-1', 'cp1252', 'utf-16-le']
        _tmp2  = None
        try:
            with _tf2.NamedTemporaryFile(suffix='.p12', delete=False) as _t:
                _t.write(p12_bytes)
                _tmp2 = _t.name
            for _enc in _encs:
                try:
                    signer = signers.SimpleSigner.load_pkcs12(
                        pfx_file   = _tmp2,
                        passphrase = password.encode(_enc),
                    )
                    break
                except Exception:
                    continue
        finally:
            if _tmp2 and os.path.exists(_tmp2):
                os.unlink(_tmp2)

        if signer is None:
            raise RuntimeError(
                "No se pudo cargar el certificado. Verifique la contraseña y "
                "que el archivo .p12 sea válido."
            )

    # ── Leer coordenadas del JSON generado por generar_pdf ───────
    try:
        with open(json_path, "r", encoding="utf-8") as jf:
            sig_map = json.load(jf)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo leer el mapa de coordenadas: {exc}")

    if campo_firma not in sig_map:
        # Fallback para campos nuevos (ej: servidor_saliente) en PDFs ya generados.
        # Se coloca la firma en el margen inferior derecho de la última página del PDF.
        try:
            from pyhanko.pdf_utils.reader import PdfFileReader as _PdfRfb
            with open(src_path, "rb") as _fbrb:
                _rdr = _PdfRfb(_fbrb)
                _last_page = max(0, _rdr.get_num_pages() - 1)
        except Exception:
            _last_page = 0
        # Posición: esquina inferior-derecha, ancho 160 pts, alto 80 pts
        sig_map[campo_firma] = (395, 50, 555, 130, _last_page)
        print(f"[pyhanko] Fallback coords para '{campo_firma}': página {_last_page}")

    coords   = sig_map[campo_firma]          # [x1, y1, x2, y2, page]
    SIG_BOX  = (coords[0], coords[1], coords[2], coords[3])
    SIG_PAGE = int(coords[4])                # 0-indexed

    # ── Apariencia visual del sello en el PDF (nativo pyHanko) ────
    # QR apunta a https://validar.firmaec.ec (portal oficial de validación).
    # El PDF firmado con el certificado FirmaEC real puede verificarse ahí.
    qr_url      = "https://validar.firmaec.ec"
    nombre_disp = signer_name[:60] if len(signer_name) > 60 else signer_name
    stamp_style = QRStampStyle(
        stamp_text=(
            "Validar únicamente en FirmaEC.\n"
            "Firmado electrónicamente por:\n"
            "%(signer)s"
        ),
        text_box_style=TextBoxStyle(
            font_size  = 9,
            text_color = (0.0, 0.12, 0.51),
        ),
        background_opacity = 1.0,
        border_width       = 1,
    )

    # ── Escribir PDF firmado (incremental) ───────────────────────
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

        # Usar ETSI.CAdES.detached para máxima compatibilidad con FirmaEC Desktop 5.x
        try:
            from pyhanko.sign.fields import SigSeedSubFilter as _SF
            _subfilter = _SF.ETSI_CADES_DETACHED
        except Exception:
            _subfilter = None

        meta = PdfSignatureMetadata(
            field_name = FIELD_NAME,
            reason     = f"Paz y Salvo INAMHI — {campo_firma}",
            location   = "Ecuador",
            name       = signer_name,
            certify    = False,
            **({'subfilter': _subfilter} if _subfilter is not None else {}),
        )

        pdf_signer_obj = PdfSigner(meta, signer, stamp_style=stamp_style)
        out_buf = _io.BytesIO()
        _sign_kw = dict(
            existing_fields_only=False,
            output=out_buf,
            appearance_text_params={'url': qr_url, 'signer': nombre_disp},
        )
        import inspect as _insp
        if _insp.iscoroutinefunction(pdf_signer_obj.sign_pdf):
            import asyncio as _aio
            _aio.run(pdf_signer_obj.sign_pdf(writer, **_sign_kw))
        else:
            pdf_signer_obj.sign_pdf(writer, **_sign_kw)
    finally:
        if not use_tmp:
            in_stream.close()

    with open(dst_path, "wb") as f_out:
        f_out.write(out_buf.getvalue())


if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True, use_reloader=False)