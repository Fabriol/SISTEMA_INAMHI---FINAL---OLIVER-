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
                u.rol,
                COUNT(a.id)                                                     AS total_asignados,
                SUM(CASE WHEN a.estado = 'CULMINADO'  THEN 1 ELSE 0 END)        AS completados,
                SUM(CASE WHEN a.estado != 'CULMINADO' THEN 1 ELSE 0 END)        AS pendientes
            FROM formulario_asignaciones a
            INNER JOIN formularios  f ON f.id = a.formulario_id
            INNER JOIN usuarios     u ON u.id = a.asignado_usuario_id
            GROUP BY
                f.id, f.titulo, f.estado, f.porcentaje,
                u.id, u.nombres, u.apellidos, u.usuario, u.rol
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
                "usuario_id":      fila["usuario_id"],
                "nombre_completo": fila["nombre_completo"],
                "nombres":         fila["nombres"],
                "apellidos":       fila["apellidos"],
                "usuario":         fila["usuario"],
                "rol":             fila["rol"],
                "total_asignados": int(fila["total_asignados"] or 0),
                "completados":     int(fila["completados"]      or 0),
                "pendientes":      int(fila["pendientes"]       or 0),
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
    Incluye listado de campos específicos pendientes, nombre completo del remitente,
    deduplicación (no reenvía si hay un recordatorio sin leer del mismo formulario)
    y registro completo en auditoría.
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

        # ── Verificar usuario destino ────────────────────────────────────────
        cursor.execute(
            "SELECT id, nombres, apellidos, rol FROM usuarios WHERE id = %s AND estado = 'ACTIVO'",
            (usuario_id,)
        )
        dest = cursor.fetchone()
        if not dest:
            return jsonify({"mensaje": "Usuario destino no encontrado o inactivo"}), 404

        # ── Verificar formulario ─────────────────────────────────────────────
        cursor.execute("SELECT id, titulo FROM formularios WHERE id = %s", (formulario_id,))
        form = cursor.fetchone()
        if not form:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        # ── Obtener nombre completo del remitente ────────────────────────────
        cursor.execute(
            "SELECT nombres, apellidos FROM usuarios WHERE id = %s LIMIT 1",
            (user["id"],)
        )
        remitente_row = cursor.fetchone()
        if remitente_row:
            remitente_nombre = f"{remitente_row['nombres']} {remitente_row['apellidos']}".strip()
        else:
            remitente_nombre = user["usuario"]

        # ── Obtener campos pendientes específicos ────────────────────────────
        cursor.execute("""
            SELECT p.codigo, p.pregunta, p.seccion
            FROM formulario_asignaciones a
            INNER JOIN formulario_preguntas p ON p.id = a.pregunta_id
            WHERE a.formulario_id = %s
              AND a.asignado_usuario_id = %s
              AND a.estado != 'CULMINADO'
            ORDER BY p.seccion, p.orden
        """, (formulario_id, usuario_id))
        campos_pend = cursor.fetchall()
        n_pendientes = len(campos_pend)

        if n_pendientes == 0:
            return jsonify({
                "mensaje": "Este usuario no tiene campos pendientes en este formulario."
            }), 400

        # ── Anti-duplicados: bloquear si ya hay un recordatorio sin leer ────
        cursor.execute("""
            SELECT id FROM notificaciones
            WHERE usuario_id = %s
              AND leido = 0
              AND titulo LIKE %s
            LIMIT 1
        """, (usuario_id, f"%{form['titulo']}%"))
        ya_existe = cursor.fetchone()
        if ya_existe:
            nombre_dest = f"{dest['nombres']} {dest['apellidos']}".strip()
            return jsonify({
                "mensaje": (
                    f"{nombre_dest} ya tiene un recordatorio sin leer para este formulario. "
                    "Espera a que lo lea antes de enviar otro."
                )
            }), 409

        # ── Construir lista de campos para el mensaje ────────────────────────
        nombre_dest = f"{dest['nombres']} {dest['apellidos']}".strip()
        codigos = [cp.get("codigo") or cp.get("pregunta") or "campo" for cp in campos_pend]
        MAX_CAMPOS_MSG = 10
        if len(codigos) <= MAX_CAMPOS_MSG:
            lista_campos_str = ", ".join(codigos)
        else:
            lista_campos_str = ", ".join(codigos[:MAX_CAMPOS_MSG]) + f" y {len(codigos) - MAX_CAMPOS_MSG} más"

        # ── Construir título y cuerpo de la notificación ─────────────────────
        titulo_notif = (
            f"Recordatorio: tienes {n_pendientes} campo(s) pendiente(s) "
            f"en «{form['titulo']}»"
        )
        msg_notif = (
            f"Tienes {n_pendientes} campo(s) sin completar en el formulario "
            f"«{form['titulo']}».\n"
            f"Campos pendientes: {lista_campos_str}.\n"
            f"Por favor ingresa al sistema, abre el formulario y completa la información."
            f"\nRecordatorio enviado por: {remitente_nombre} ({user['rol']})."
        )
        if mensaje_extra:
            msg_notif += f"\nMensaje adicional: {mensaje_extra}"

        # ── Insertar notificación ────────────────────────────────────────────
        cursor.execute("""
            INSERT INTO notificaciones (usuario_id, rol_destino, titulo, mensaje, leido)
            VALUES (%s, NULL, %s, %s, 0)
        """, (usuario_id, titulo_notif, msg_notif))

        conn.commit()

        # ── Auditoría ────────────────────────────────────────────────────────
        registrar_auditoria(
            user["usuario"], user["rol"], "Reportes",
            "Recordatorio enviado",
            (
                f"Recordatorio enviado a {nombre_dest} (ID {usuario_id}) "
                f"por formulario ID {formulario_id} «{form['titulo']}» — "
                f"{n_pendientes} campo(s) pendiente(s): {lista_campos_str}"
            )
        )

        return jsonify({
            "mensaje":    f"Recordatorio enviado correctamente a {nombre_dest}.",
            "destinatario": nombre_dest,
            "pendientes": n_pendientes,
            "campos":     codigos,
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
        _precrear_todas_preguntas(formulario_id, cursor)
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
                LEFT JOIN formulario_respuestas r ON p.id = r.pregunta_id AND r.formulario_id = p.formulario_id
                WHERE p.formulario_id = %s
                ORDER BY p.orden ASC, p.id ASC
            """, (id,))
        else:
            # Devuelve TODAS las preguntas del formulario con sus respuestas guardadas
            # (para que la hoja espejo muestre el formulario completo), pero marca
            # solo las del usuario actual como editables (es_mio = 1).
            cursor.execute("""
                SELECT
                    p.*,
                    a.id          AS asignacion_id,
                    a.asignado_usuario_id,
                    a.estado      AS estado_asignacion,
                    r.respuesta,
                    CASE WHEN a.asignado_usuario_id = %s THEN 1 ELSE 0 END AS es_mio
                FROM formulario_preguntas p
                LEFT JOIN formulario_asignaciones a
                       ON p.id = a.pregunta_id AND a.asignado_usuario_id = %s
                LEFT JOIN formulario_respuestas r ON p.id = r.pregunta_id AND r.formulario_id = p.formulario_id
                WHERE p.formulario_id = %s
                ORDER BY p.orden ASC, p.id ASC
            """, (user["id"], user["id"], id))

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

        # Garantiza que existan todas las preguntas estándar antes de asignar
        _precrear_todas_preguntas(formulario_id, cursor)

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
            SELECT id, tipo FROM formulario_preguntas
            WHERE formulario_id = %s AND codigo = %s
            LIMIT 1
        """, (formulario_id, campo))
        pregunta = cursor.fetchone()

        if not pregunta:
            # Fallback: búsqueda insensible a mayúsculas/minúsculas
            cursor.execute("""
                SELECT id, tipo FROM formulario_preguntas
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

        pregunta_id  = pregunta["id"]
        pregunta_tipo = (pregunta.get("tipo") or "TEXTO").upper().strip()

        # ── 1b. Validación de tipo (solo para respuestas que no son firmas) ──
        if not (respuesta.startswith("data:") or respuesta.upper().startswith("FIRMADO_EC:")):
            if len(respuesta) > 10000:
                return jsonify({"mensaje": "La respuesta excede la longitud máxima permitida (10000 caracteres)"}), 400
            if pregunta_tipo in ("NUMERO", "NUMBER"):
                try:
                    _num = float(respuesta.replace(",", "."))
                    if _num < 0:
                        return jsonify({"mensaje": f"El campo '{campo}' no acepta valores negativos"}), 400
                except (ValueError, TypeError):
                    return jsonify({"mensaje": f"El campo '{campo}' requiere un valor numérico válido"}), 400
            elif pregunta_tipo in ("FECHA", "DATE"):
                from datetime import datetime as _dt
                try:
                    _dt.strptime(respuesta, "%Y-%m-%d")
                except ValueError:
                    return jsonify({"mensaje": f"El campo '{campo}' requiere una fecha con formato YYYY-MM-DD"}), 400

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
            # Permitir si el usuario tiene AL MENOS UNA asignación en este formulario
            # (los campos estándar pre-creados no tienen asignación individual pero
            #  pertenecen a la sección del usuario que completó el formulario)
            cursor.execute("""
                SELECT id FROM formulario_asignaciones
                WHERE formulario_id = %s AND asignado_usuario_id = %s
                LIMIT 1
            """, (formulario_id, user["id"]))
            alguna_asignacion = cursor.fetchone()
            if not alguna_asignacion:
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
#  CATÁLOGO COMPLETO DE CAMPOS — PAZ Y SALVO
#  Todos los campos que aparecen en la HOJA ESPEJO A4 y en el PDF.
#  Usados para pre-crear preguntas al asignar/crear un formulario.
# ═══════════════════════════════════════════════════════════════
ALL_PDF_CAMPOS = [
    # 01 — Datos Personales
    ("nombres_apellidos",    "Nombres y Apellidos",                    "TEXTO",  "Datos Personales",      0),
    ("cedula",               "Cédula / Pasaporte",                     "TEXTO",  "Datos Personales",      1),
    ("modalidad",            "Modalidad Laboral",                      "SELECT", "Datos Personales",      2),
    ("fecha_ingreso",        "Fecha de Ingreso",                       "FECHA",  "Datos Personales",      3),
    ("fecha_salida",         "Fecha de Salida",                        "FECHA",  "Datos Personales",      4),
    ("direccion",            "Dirección Domiciliaria",                 "TEXTO",  "Datos Personales",      5),
    ("numero_domicilio",     "Número Domicilio",                       "TEXTO",  "Datos Personales",      6),
    ("celular",              "Número Celular",                         "TEXTO",  "Datos Personales",      7),
    ("emergencia",           "Contacto Emergencia",                    "TEXTO",  "Datos Personales",      8),
    ("email1",               "Email Principal",                        "TEXTO",  "Datos Personales",      9),
    ("email2",               "Email Secundario",                       "TEXTO",  "Datos Personales",     10),
    ("provincia",            "Provincia",                              "TEXTO",  "Datos Personales",     11),
    ("canton",               "Cantón",                                 "TEXTO",  "Datos Personales",     12),
    # 02 — Dirección / Unidad
    ("lugar_trabajo",        "Lugar de Trabajo",                       "SELECT", "Dirección / Unidad",   20),
    ("unidad",               "Dirección / Unidad",                     "TEXTO",  "Dirección / Unidad",   21),
    ("cargo",                "Cargo Desempeñado",                      "TEXTO",  "Dirección / Unidad",   22),
    ("grupo_ocupacional",    "Grupo Ocupacional",                      "SELECT", "Dirección / Unidad",   23),
    # 03 — Trámites y Unidad
    ("tramites_informe",           "Entrega informe fin de gestión",             "SELECT", "Trámites y Unidad",    30),
    ("tramites_quipux_cero",       "QUIPUX Bandeja en Cero",                     "SELECT", "Trámites y Unidad",    31),
    ("tramites_nombre_resp1",      "Nombre Responsable Trámites Fila 1",         "TEXTO",  "Trámites y Unidad",    32),
    ("tramites_r1",                "FirmaEC — Trámites: Fila 1",                 "FIRMA",  "Trámites y Unidad",    33),
    ("tramites_fe_presentacion",   "Fe de presentación",                         "SELECT", "Trámites y Unidad",    34),
    ("tramites_claves_asignadas",  "Claves de acceso asignadas",                 "SELECT", "Trámites y Unidad",    35),
    ("tramites_nombre_resp2",      "Nombre Responsable Trámites Fila 2",         "TEXTO",  "Trámites y Unidad",    36),
    ("tramites_r2",                "FirmaEC — Trámites: Fila 2",                 "FIRMA",  "Trámites y Unidad",    37),
    ("tramites_losep",             "Entrega archivo físico y digital (LOSEP)",   "SELECT", "Trámites y Unidad",    38),
    ("tramites_acta_claves",       "Acta entrega de claves",                     "SELECT", "Trámites y Unidad",    39),
    ("tramites_nombre_resp3",      "Nombre Responsable Trámites Fila 3",         "TEXTO",  "Trámites y Unidad",    40),
    ("tramites_r3",                "FirmaEC — Trámites: Fila 3",                 "FIRMA",  "Trámites y Unidad",    41),
    ("tramites_admin_contrato",    "¿Es Administrador de Contrato?",             "SELECT", "Trámites y Unidad",    42),
    ("tramites_desc_contrato",     "Descripción del contrato",                   "TEXTO",  "Trámites y Unidad",    43),
    ("tramites_memo",              "Número Memorando nuevo admin",               "TEXTO",  "Trámites y Unidad",    44),
    ("tramites_jefe_inmediato",    "Nombre del Jefe Inmediato",                  "TEXTO",  "Trámites y Unidad",    45),
    ("tramites_servidor_recibe",   "Servidor que recibe trámites",               "TEXTO",  "Trámites y Unidad",    46),
    ("tramites_obs",               "Observación Trámites",                       "TEXTO",  "Trámites y Unidad",    47),
    ("tramites_nombre_responsable","Nombre Responsable Trámites (Jefe)",         "TEXTO",  "Trámites y Unidad",    48),
    ("tramites_jefe",              "FirmaEC — Trámites: Jefe Inmediato",         "FIRMA",  "Trámites y Unidad",    49),
    # 04 — Gestión Administrativa
    ("admin_informe",          "¿Realizó entrega de informe?",              "SELECT", "Gestión Administrativa",  50),
    ("admin_nombre_resp1",     "Nombre Responsable Admin Fila 1",           "TEXTO",  "Gestión Administrativa",  51),
    ("admin_r1",               "FirmaEC — Administrativa: Fila 1",          "FIRMA",  "Gestión Administrativa",  52),
    ("admin_bienes",           "¿Entregó bienes y muebles?",                "SELECT", "Gestión Administrativa",  53),
    ("admin_valor_bienes",     "Valor a Descontar (Bienes)",                 "NUMERO", "Gestión Administrativa",  54),
    ("admin_acta_bienes",      "Acta de Entrega de Bienes",                  "TEXTO",  "Gestión Administrativa",  541),
    ("admin_nombre_resp2",     "Nombre Responsable Admin Fila 2",           "TEXTO",  "Gestión Administrativa",  55),
    ("admin_r2",               "FirmaEC — Administrativa: Fila 2",          "FIRMA",  "Gestión Administrativa",  56),
    ("admin_deducibles",       "¿Tiene Deducibles Pendientes?",             "SELECT", "Gestión Administrativa",  57),
    ("admin_deducibles_valor", "Valor Deducibles",                          "NUMERO", "Gestión Administrativa",  58),
    ("admin_nombre_resp3",     "Nombre Responsable Admin Fila 3",           "TEXTO",  "Gestión Administrativa",  59),
    ("admin_r3",               "FirmaEC — Administrativa: Fila 3",          "FIRMA",  "Gestión Administrativa",  60),
    ("admin_pasajes",          "¿Pasajes aéreos por justificar?",           "SELECT", "Gestión Administrativa",  61),
    ("admin_pasajes_valor",    "Valor a Descontar (Pasajes)",               "NUMERO", "Gestión Administrativa",  62),
    ("admin_nombre_resp4",     "Nombre Responsable Admin Fila 4",           "TEXTO",  "Gestión Administrativa",  63),
    ("admin_r4",               "FirmaEC — Administrativa: Fila 4",          "FIRMA",  "Gestión Administrativa",  64),
    ("admin_responsable",      "Director/a Administrativo/a Financiero/a", "TEXTO",  "Gestión Administrativa",  65),
    ("admin_dir",              "FirmaEC — Administrativa: Director/a",      "FIRMA",  "Gestión Administrativa",  66),
    # 05 — Gestión TIC
    ("tic_verificacion",      "Verificación Equipo / IP / accesos",         "SELECT", "Gestión TIC",  70),
    ("tic_ip_fija",           "Acceso IP Fija",                             "SELECT", "Gestión TIC",  71),
    ("tic_liberacion",        "Liberación de IP",                          "SELECT", "Gestión TIC",  72),
    ("tic_nombre_resp1",      "Nombre Responsable TIC Fila 1",              "TEXTO",  "Gestión TIC",  73),
    ("tic_r1",                "FirmaEC — TIC: Fila 1",                      "FIRMA",  "Gestión TIC",  74),
    ("tic_backup",            "Entrega Backup de Información",              "SELECT", "Gestión TIC",  75),
    ("tic_ruta_backup",       "Ruta del Backup",                            "TEXTO",  "Gestión TIC",  76),
    ("tic_nombre_resp2",      "Nombre Responsable TIC Fila 2",              "TEXTO",  "Gestión TIC",  77),
    ("tic_r2",                "FirmaEC — TIC: Fila 2",                      "FIRMA",  "Gestión TIC",  78),
    ("tic_retiro_acceso",     "Retiro control acceso / contraseñas",        "SELECT", "Gestión TIC",  79),
    ("tic_cierre_correo",     "Cierre Correo Institucional",                "SELECT", "Gestión TIC",  80),
    ("tic_esigef",            "Cierre eSIGEF",                              "SELECT", "Gestión TIC",  81),
    ("tic_quipux",            "Cierre QUIPUX",                             "SELECT", "Gestión TIC",  82),
    ("tic_spryn",             "Cierre SPRYN",                               "SELECT", "Gestión TIC",  83),
    ("tic_esbye",             "Cierre eSByE",                               "SELECT", "Gestión TIC",  84),
    ("tic_nombre_resp3",      "Nombre Responsable TIC Fila 3",              "TEXTO",  "Gestión TIC",  85),
    ("tic_r3",                "FirmaEC — TIC: Fila 3",                      "FIRMA",  "Gestión TIC",  86),
    ("tic_tarjeta_cuentas",   "Entrega y Desactivación Tarjeta Acceso",     "SELECT", "Gestión TIC",  87),
    ("tic_obs",               "Observación TIC",                           "TEXTO",  "Gestión TIC",  88),
    ("tic_nombre_resp4",      "Nombre Responsable TIC Fila 4",              "TEXTO",  "Gestión TIC",  89),
    ("tic_r4",                "FirmaEC — TIC: Fila 4",                      "FIRMA",  "Gestión TIC",  90),
    ("tic_responsable",       "Responsable TIC",                           "TEXTO",  "Gestión TIC",  91),
    ("tic_r5",                "FirmaEC — TIC: Fila 5 (Director/a)",         "FIRMA",  "Gestión TIC",  92),
    # 06 — Gestión Financiera
    ("fin_saldos",            "Saldos Contables Pendientes",               "SELECT", "Gestión Financiera",  100),
    ("fin_saldos_valor",      "Valor Saldos Contables",                    "NUMERO", "Gestión Financiera",  101),
    ("fin_saldos_obs",        "Observación Saldos",                        "TEXTO",  "Gestión Financiera",  102),
    ("fin_nombre_resp1",      "Nombre Responsable Financiero Fila 1",      "TEXTO",  "Gestión Financiera",  103),
    ("fin_r1",                "FirmaEC — Financiera: Fila 1",              "FIRMA",  "Gestión Financiera",  104),
    ("fin_anticipo",          "Anticipo de Sueldos Pendiente",             "SELECT", "Gestión Financiera",  105),
    ("fin_anticipo_valor",    "Valor Anticipo Sueldos",                    "NUMERO", "Gestión Financiera",  106),
    ("fin_anticipo_obs",      "Observación Anticipo",                      "TEXTO",  "Gestión Financiera",  107),
    ("fin_nombre_resp2",      "Nombre Responsable Financiero Fila 2",      "TEXTO",  "Gestión Financiera",  108),
    ("fin_r2",                "FirmaEC — Financiera: Fila 2",              "FIRMA",  "Gestión Financiera",  109),
    ("fin_recuperacion",      "Recuperación de Valores Pendiente",         "SELECT", "Gestión Financiera",  110),
    ("fin_recuperacion_valor","Valor Recuperación",                        "NUMERO", "Gestión Financiera",  111),
    ("fin_recuperacion_obs",  "Observación Recuperación",                  "TEXTO",  "Gestión Financiera",  112),
    ("fin_nombre_resp3",      "Nombre Responsable Financiero Fila 3",      "TEXTO",  "Gestión Financiera",  113),
    ("fin_r3",                "FirmaEC — Financiera: Fila 3",              "FIRMA",  "Gestión Financiera",  114),
    ("fin_devolucion",        "Devolución Muebles / Equipos",              "SELECT", "Gestión Financiera",  115),
    ("fin_devolucion_valor",  "Valor Devolución Muebles",                  "NUMERO", "Gestión Financiera",  116),
    ("fin_devolucion_obs",    "Observación Devolución",                    "TEXTO",  "Gestión Financiera",  117),
    ("fin_nombre_resp4",      "Nombre Responsable Financiero Fila 4",      "TEXTO",  "Gestión Financiera",  118),
    ("fin_r4",                "FirmaEC — Financiera: Fila 4",              "FIRMA",  "Gestión Financiera",  119),
    ("fin_director",          "Director/a Administrativo/a Financiero/a",  "TEXTO",  "Gestión Financiera",  120),
    ("fin_dir",               "FirmaEC — Financiera: Director/a",          "FIRMA",  "Gestión Financiera",  121),
    # 07 — Seguridad de la Información
    ("seg_archivos",           "Archivos Digitales (EGSI)",                       "SELECT", "Seguridad",  130),
    ("seg_entrega_copia",      "Entrega Copia de Informe de Actividades",         "SELECT", "Seguridad",  131),
    ("seg_nombre_resp1",       "Nombre Responsable Seguridad Fila 1",             "TEXTO",  "Seguridad",  132),
    ("seg_r1",                 "FirmaEC — Seguridad: Fila 1",                     "FIRMA",  "Seguridad",  133),
    ("seg_archivos_fisicos",   "Archivos Físicos (Archivo Central)",              "SELECT", "Seguridad",  134),
    ("seg_verificacion_info",  "Verificación Información Institucional",          "SELECT", "Seguridad",  135),
    ("seg_nombre_resp2",       "Nombre Responsable Seguridad Fila 2",             "TEXTO",  "Seguridad",  136),
    ("seg_r2",                 "FirmaEC — Seguridad: Fila 2",                     "FIRMA",  "Seguridad",  137),
    ("seg_oficial",            "Oficial de Seguridad Institucional",              "TEXTO",  "Seguridad",  138),
    ("seg_responsable",        "Nombre Responsable Seguridad",                    "TEXTO",  "Seguridad",  139),
    # 08 — Dirección de Administración de RRHH
    ("rrhh_capacitacion",       "Capacitación: devengó cursos recibidos",         "SELECT", "Recursos Humanos",  150),
    ("rrhh_cursos_eval",        "N° Cursos / Calificación Evaluación",            "SELECT", "Recursos Humanos",  1502),
    ("rrhh_resp_capacitacion",  "Nombre Responsable Capacitación",                "TEXTO",  "Recursos Humanos",  151),
    ("rrhh_r1",                 "FirmaEC — RRHH: Fila 1",                         "FIRMA",  "Recursos Humanos",  152),
    ("rrhh_evaluacion",         "Evaluación del Desempeño aplicada",              "SELECT", "Recursos Humanos",  153),
    ("rrhh_resp_evaluacion",    "Nombre Responsable Evaluación",                  "TEXTO",  "Recursos Humanos",  154),
    ("rrhh_r2",                 "FirmaEC — RRHH: Fila 2",                         "FIRMA",  "Recursos Humanos",  155),
    ("rrhh_viajes",             "Viajes al exterior: devengación",                "SELECT", "Recursos Humanos",  156),
    ("rrhh_resp_viajes",        "Nombre Responsable Viajes al Exterior",          "TEXTO",  "Recursos Humanos",  157),
    ("rrhh_r3",                 "FirmaEC — RRHH: Fila 3",                         "FIRMA",  "Recursos Humanos",  158),
    ("rrhh_siith",              "SIITH: desvinculación del sistema",              "SELECT", "Recursos Humanos",  159),
    ("rrhh_resp_siith",         "Nombre Responsable SIITH",                       "TEXTO",  "Recursos Humanos",  160),
    ("rrhh_r4",                 "FirmaEC — RRHH: Fila 4",                         "FIRMA",  "Recursos Humanos",  161),
    ("rrhh_juramentada",        "Declaración juramentada de bienes",              "SELECT", "Recursos Humanos",  162),
    ("rrhh_num_declaracion",    "N° Declaración Juramentada",                     "TEXTO",  "Recursos Humanos",  163),
    ("rrhh_resp_juramentada",   "Nombre Responsable Declaración Juramentada",     "TEXTO",  "Recursos Humanos",  164),
    ("rrhh_r6",                 "FirmaEC — RRHH: Fila 6",                         "FIRMA",  "Recursos Humanos",  165),
    ("rrhh_credencial",         "Credencial institucional / Porta cred.",         "SELECT", "Recursos Humanos",  166),
    ("rrhh_resp_credencial2",   "Nombre Responsable Credencial / Copia Act.",     "TEXTO",  "Recursos Humanos",  167),
    ("rrhh_r7",                 "FirmaEC — RRHH: Fila 7",                         "FIRMA",  "Recursos Humanos",  168),
    ("rrhh_entrega_informe_cd", "Entrega copia de actividades en CD",             "SELECT", "Recursos Humanos",  169),
    ("rrhh_ropa_trabajo",       "Entrega de ropa de trabajo",                     "SELECT", "Recursos Humanos",  1692),
    ("rrhh_acta_bienes",        "Acta de bienes del custodio",                    "SELECT", "Recursos Humanos",  170),
    ("rrhh_resp_acta",          "Nombre Responsable Acta Bienes / Ropa",          "TEXTO",  "Recursos Humanos",  171),
    ("rrhh_r8",                 "FirmaEC — RRHH: Fila 8",                         "FIRMA",  "Recursos Humanos",  172),
    ("rrhh_vacaciones",         "Días Vacaciones Acumuladas No Gozadas",          "NUMERO", "Recursos Humanos",  173),
    ("rrhh_num_certificado",    "N° Certificado Emitido",                         "TEXTO",  "Recursos Humanos",  174),
    ("rrhh_resp_vacaciones",    "Nombre Responsable Vacaciones RRHH",             "TEXTO",  "Recursos Humanos",  175),
    ("rrhh_r5",                 "FirmaEC — RRHH: Fila 5 (Vacaciones)",            "FIRMA",  "Recursos Humanos",  176),
    ("rrhh_director",           "Director/a de Administración de RRHH",          "TEXTO",  "Recursos Humanos",  177),
    ("rrhh_dir",                "FirmaEC — RRHH: Director/a",                    "FIRMA",  "Recursos Humanos",  178),
    # 09 — Recepción de Documentos
    ("recepcion_fecha",    "Fecha de Entrega Paz y Salvo",                "FECHA",  "Recepción",  190),
    ("recepcion_hojas",    "N° Hojas Recibidas",                          "NUMERO", "Recepción",  191),
    ("recepcion_servidor", "Servidor/a que recibe",                       "TEXTO",  "Recepción",  192),
    ("recepcion_cargo",    "Cargo del Servidor/a",                        "TEXTO",  "Recepción",  193),
    ("recepcion_r1",       "FirmaEC — Recepción: Servidor/a que recibe",  "FIRMA",  "Recepción",  194),
    # 10 — Autorización — Servidor Saliente
    ("cedula_firmante",    "C.C. del Firmante",                            "TEXTO",  "Firma",  200),
    ("fecha_firma",        "Fecha de Firma",                               "FECHA",  "Firma",  201),
    ("servidor_saliente",  "FirmaEC — Autorización: Servidor Saliente",   "FIRMA",  "Firma",  202),
]


def _precrear_todas_preguntas(formulario_id, cursor):
    """
    Inserta en formulario_preguntas TODOS los campos estándar del Paz y Salvo
    para el formulario indicado, si no existen todavía.

    No crea asignaciones — solo garantiza que el código del campo exista
    en la tabla para que el PDF y el endpoint /responder siempre lo encuentren.
    """
    for (codigo, pregunta, tipo, seccion, orden) in ALL_PDF_CAMPOS:
        cursor.execute("""
            SELECT id FROM formulario_preguntas
            WHERE formulario_id = %s AND codigo = %s LIMIT 1
        """, (formulario_id, codigo))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO formulario_preguntas
                (formulario_id, codigo, pregunta, tipo, seccion, opciones, obligatorio, orden)
                VALUES (%s, %s, %s, %s, %s, NULL, 0, %s)
            """, (formulario_id, codigo, pregunta, tipo, seccion, orden))


# ═══════════════════════════════════════════════════════════════
#  PDF PAZ Y SALVO — HOJA ESPEJO (idéntico al frontend Angular)
# ═══════════════════════════════════════════════════════════════
#  A4 = 595.28 × 841.89 pts.  Origen (0,0) = esquina inferior-izquierda.

# ════════════════════════════════════════════════════════════════════════════════
#  PDF PAZ Y SALVO — RÉPLICA EXACTA DE LA HOJA ESPEJO DEL FRONTEND ANGULAR
#  A4 = 595.28 × 841.89 pts  ·  Origen (0,0) = esquina inferior-izquierda
# ════════════════════════════════════════════════════════════════════════════════

# ── Márgenes ──────────────────────────────────────────────────────────────────
_ML  = 20          # margen izquierdo
_MR  = 575         # margen derecho (595 - 20)
_CW  = 555         # ancho contenido (_MR - _ML)
_MT  = 776         # Y inicial del contenido (debajo del header de 57 pts)
_MB  = 42          # Y mínima antes de salto de página (pie de página)

# ── Columna FIRMA siempre al extremo derecho: 22% de 555 = 122 pts ────────────
_FX1 = 453         # x inicio columna firma  (575 - 122 = 453)
_FX2 = 575         # x fin   columna firma
_FW  = 122         # ancho   columna firma
_FRH = 68          # altura de fila firma (amplia para QR completo + texto)

# ── Tabla 6 col: Trámites y Seguridad  (22|5|22|5|24|22 %) ───────────────────
# Anchos: 122+28+122+28+133+122 = 555
_T6W = [122, 28, 122, 28, 133, 122]
_T6X = [20, 142, 170, 292, 320, 453]
_T6L = ["DESCRIPCIÓN", "S/N", "DESCRIPCIÓN", "S/N",
        "NOMBRE RESPONSABLE", "FIRMA ELECTRÓNICA"]

# ── Tabla 5 col: Admin, TIC, Fin, RRHH  (29|5|22|22|22 %) ───────────────────
# Anchos: 161+28+122+122+122 = 555
_T5W = [161, 28, 122, 122, 122]
_T5X = [20, 181, 209, 331, 453]
_T5L = ["DESCRIPCIÓN", "S/N", "DATO ADICIONAL",
        "NOMBRE RESPONSABLE", "FIRMA ELECTRÓNICA"]

# ── Tabla info 4 col: Datos Personales  (16|34|16|34 %) ──────────────────────
# Anchos: 89+189+89+188 = 555
_I4W = [89, 189, 89, 188]
_I4X = [20, 109, 298, 387]

# ── Alturas ───────────────────────────────────────────────────────────────────
_BH  = 20    # cabecera de bloque (azul oscuro)
_CH  = 15    # cabecera de columnas (azul medio)
_IH  = 16    # fila info (datos personales)

# ── Paleta de colores — extraída exactamente del CSS de la hoja espejo ────────
# ep-bloque__head background: #122d5e
_C_HEAD  = (18/255,  45/255,  94/255)
# ep-tabla-firmas th background: #2d579c
_C_COLS  = (45/255,  87/255, 156/255)
# ep-th background: #e8edf8
_C_TH    = (232/255, 237/255, 248/255)
_C_WHITE = (1.0, 1.0, 1.0)
_C_BLACK = (0.0, 0.0, 0.0)
# SI badge: #16a34a (verde)
_C_SI    = (22/255, 163/255, 74/255)
# NO badge: #dc2626 (rojo)
_C_NO    = (220/255, 38/255, 38/255)
# texto SI/NO oscuro
_C_SI_T  = (4/255, 120/255, 87/255)
_C_NO_T  = (185/255, 28/255, 28/255)
_C_PEND  = (0.55, 0.55, 0.55)
# fila director: fondo muy tenue azul
_C_DIRFG = (0.95, 0.96, 1.0)
# compatibilidad con código existente
_C_GRAY  = (0.96, 0.96, 0.96)
_C_MR    = _MR   # alias


# ── Colores por sección — extraídos exactamente del CSS del espejo HTML ──────
# Cada sección tiene su propio color de cabecera, como en ep-bloque--* del CSS
_CS_P    = (30/255,  58/255, 138/255)   # 01 Datos Personales   #1e3a8a
_CS_U    = (29/255,  78/255, 216/255)   # 02 Dirección/Unidad   #1d4ed8
_CS_T    = ( 3/255, 105/255, 161/255)   # 03 Trámites           #0369a1
_CS_A    = (55/255,  65/255,  81/255)   # 04 Administrativo     #374151
_CS_TIC  = (67/255,  56/255, 202/255)   # 05 TIC                #4338ca
_CS_FIN  = ( 6/255,  95/255,  70/255)   # 06 Financiero         #065f46
_CS_SEG  = (146/255, 64/255,  14/255)   # 07 Seguridad          #92400e
_CS_RRHH = (30/255,  58/255, 138/255)   # 08 RRHH               #1e3a8a
_CS_REC  = (20/255,  83/255,  45/255)   # 09 Recepción          #14532d
_CS_AUTH = (76/255,  29/255, 149/255)   # 10 Autorización       #4c1d95

# ── Colores de cabeceras de columna (ligeramente más claros que el header) ───
_CC_T    = ( 7/255, 128/255, 179/255)   # 03 Trámites col header
_CC_A    = (71/255,  85/255,  99/255)   # 04 Admin col header
_CC_TIC  = (79/255,  70/255, 212/255)   # 05 TIC col header
_CC_FIN  = (10/255, 117/255,  87/255)   # 06 Fin col header
_CC_SEG  = (160/255, 80/255,  30/255)   # 07 Seg col header
_CC_RRHH = (45/255,  87/255, 156/255)   # 08 RRHH col header (azul medio)
_CC_REC  = (26/255, 107/255,  57/255)   # 09 Rec col header
_CC_AUTH = (94/255,  43/255, 165/255)   # 10 Auth col header

# ── Ruta al logo institucional ────────────────────────────────────────────────
# Intentar varias rutas posibles (assets, public, dist)
_LOGO_PATH = None
for _logo_candidate in [
    os.path.join(BASE_DIR, '..', 'frontend', 'public',   'img', 'logo.png'),
    os.path.join(BASE_DIR, '..', 'frontend', 'src', 'assets', 'img', 'logo.png'),
    os.path.join(BASE_DIR, '..', 'frontend', 'dist', 'frontend', 'browser', 'img', 'logo.png'),
    os.path.join(BASE_DIR, '..', 'frontend', 'dist', 'frontend', 'browser', 'assets', 'img', 'logo.png'),
]:
    if os.path.exists(_logo_candidate):
        _LOGO_PATH = _logo_candidate
        break


# ══════════════════════════════════════════════════════════════════════════════
#  FUNCIONES AUXILIARES DE DIBUJO
# ══════════════════════════════════════════════════════════════════════════════

def _split_text(text: str, max_chars: int) -> list:
    """
    Divide texto en líneas respetando palabras.
    max_chars: límite de caracteres por línea (aprox. ancho_celda / 4.2 con fuente 7.5pt).
    Siempre devuelve al menos una lista con un elemento.
    """
    text = str(text or "").strip()
    if not text:
        return [""]
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip() if cur else w
        if len(cand) <= max_chars:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            # Si una sola palabra es más larga que max_chars, la forzamos
            if len(w) > max_chars:
                lines.append(w[:max_chars])
                cur = ""
            else:
                cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _chars_for_width(pts: float, font_size: float = 7.5) -> int:
    """Calcula máximo de caracteres que caben en 'pts' puntos con Helvetica."""
    # Helvetica promedio: ancho ≈ 0.55 × font_size
    char_w = font_size * 0.55
    return max(int(pts / char_w), 8)


def _draw_page_header(c, formulario: dict, page_num: int) -> None:
    """
    Encabezado institucional INAMHI — 3 columnas:
      Logo (izq) | Textos institucionales (centro) | Tabla código (der)
    Réplica exacta del .ep-header del HTML angular.
    """
    W     = 595.28
    HY    = 786         # Y del borde inferior del header
    HH    = 55          # altura del header
    HTOP  = HY + HH     # Y del borde superior (841)

    # Fondo blanco del header
    c.setFillColorRGB(*_C_WHITE)
    c.rect(0, HY, W, HH, fill=1, stroke=0)

    # Franja azul superior (12 pts)
    c.setFillColorRGB(*_C_HEAD)
    c.rect(0, HTOP - 12, W, 12, fill=1, stroke=0)

    # ── Logo (izquierda) ────────────────────────────────────────────────────
    LOGO_W = 60
    LOGO_H = 36
    LOGO_X = _ML
    LOGO_Y = HY + (HH - LOGO_H) / 2 - 4
    logo_ok = False
    if _LOGO_PATH:
        try:
            from reportlab.lib.utils import ImageReader as _IR
            _logo_img = _IR(_LOGO_PATH)
            c.drawImage(_logo_img, LOGO_X, LOGO_Y,
                        width=LOGO_W, height=LOGO_H,
                        preserveAspectRatio=True, anchor='c', mask='auto')
            logo_ok = True
        except Exception:
            pass
    if not logo_ok:
        # fallback: rectángulo azul oscuro con texto INAMHI
        c.setFillColorRGB(*_C_HEAD)
        c.rect(LOGO_X, LOGO_Y, LOGO_W, LOGO_H, fill=1, stroke=0)
        c.setFillColorRGB(*_C_WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(LOGO_X + LOGO_W / 2, LOGO_Y + LOGO_H / 2 - 5, "INAMHI")

    # ── Tabla código (derecha) ───────────────────────────────────────────────
    # Replica: CÓDIGO | INAMHI-RH-001 / VERSIÓN | 2.0 / PÁGINA | N
    CT_W  = 115         # ancho total tabla código
    CT_X  = W - _ML - CT_W
    CT_Y  = HY + 6
    CT_RH = 11          # altura de cada fila
    CT_LW = 48          # ancho columna etiqueta

    c.setStrokeColorRGB(*_C_HEAD)
    c.setLineWidth(0.5)
    c.rect(CT_X, CT_Y, CT_W, CT_RH * 3, fill=0, stroke=1)
    c.line(CT_X + CT_LW, CT_Y, CT_X + CT_LW, CT_Y + CT_RH * 3)
    for i in range(1, 3):
        c.line(CT_X, CT_Y + i * CT_RH, CT_X + CT_W, CT_Y + i * CT_RH)

    c.setFillColorRGB(*_C_HEAD)
    c.setFont("Helvetica-Bold", 6.5)
    for i, (lbl, val) in enumerate([
        ("CÓDIGO",  "INAMHI-RH-001"),
        ("VERSIÓN", "2.0"),
        ("PÁGINA",  f"{page_num + 1} / 2"),
    ]):
        ry = CT_Y + (2 - i) * CT_RH + 3
        c.drawString(CT_X + 2, ry, lbl)
        c.setFillColorRGB(*_C_BLACK)
        c.setFont("Helvetica", 6.5)
        c.drawString(CT_X + CT_LW + 3, ry, val)
        c.setFillColorRGB(*_C_HEAD)
        c.setFont("Helvetica-Bold", 6.5)

    # ── Textos institucionales (centro) ─────────────────────────────────────
    CX = _ML + LOGO_W + 4
    CW = CT_X - CX - 4
    CY_BOT = HY + 8

    c.setFillColorRGB(*_C_HEAD)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawCentredString(CX + CW / 2, CY_BOT + 26,
                        "Instituto Nacional de Meteorología e Hidrología")
    c.setFont("Helvetica", 7.5)
    c.drawCentredString(CX + CW / 2, CY_BOT + 15,
                        "Dirección de Administración de Recursos Humanos")
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(CX + CW / 2, CY_BOT + 4,
                        "FORMULARIO PAZ Y SALVO — LIQUIDACIÓN DE HABERES")

    # Línea separadora entre header y contenido
    c.setStrokeColorRGB(*_C_HEAD)
    c.setLineWidth(1.2)
    c.line(_ML, HY, W - _ML, HY)
    c.setFillColorRGB(*_C_BLACK)
    c.setStrokeColorRGB(*_C_BLACK)
    c.setLineWidth(0.4)


def _sec_header(c, y: float, num: str, titulo: str,
                color: tuple = None) -> float:
    """
    Cabecera de bloque con badge de número y color configurable por sección.
    color: tuple RGB; si None usa _C_HEAD (azul oscuro).
    Réplica de .ep-bloque__head del HTML angular.
    """
    col = color or _C_HEAD
    c.setFillColorRGB(*col)
    c.rect(_ML, y - _BH, _CW, _BH, fill=1, stroke=0)
    # Badge del número — fondo blanco semitransparente sobre el color de sección
    BADGE_W = 22
    c.setFillColorRGB(*_C_WHITE)
    c.roundRect(_ML + 3, y - _BH + 3, BADGE_W, _BH - 6, 2, fill=1, stroke=0)
    # Texto del badge en el color de la sección
    c.setFillColorRGB(*col)
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(_ML + 3 + BADGE_W / 2, y - _BH + 6, num)
    # Título en blanco
    c.setFillColorRGB(*_C_WHITE)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(_ML + 3 + BADGE_W + 5, y - _BH + 6, titulo.upper())
    c.setFillColorRGB(*_C_BLACK)
    return y - _BH


def _col_header(c, y: float, xs: list, ws: list, labels: list,
                color: tuple = None) -> float:
    """
    Fila de cabeceras de columnas con color configurable por sección.
    color: tuple RGB; si None usa _C_COLS (azul medio estándar).
    """
    col = color or _C_COLS
    c.setFillColorRGB(*col)
    c.setStrokeColorRGB(*col)
    c.setLineWidth(0.4)
    for x, w in zip(xs, ws):
        c.rect(x, y - _CH, w, _CH, fill=1, stroke=1)
    c.setFillColorRGB(*_C_WHITE)
    c.setFont("Helvetica-Bold", 6)
    for lbl, x, w in zip(labels, xs, ws):
        c.drawCentredString(x + w / 2, y - _CH + 4, str(lbl))
    c.setFillColorRGB(*_C_BLACK)
    c.setStrokeColorRGB(*_C_BLACK)
    c.setLineWidth(0.4)
    return y - _CH


def _info_row(c, y: float, l1: str, v1: str,
              l2: str = "", v2: str = "", span: bool = False) -> float:
    """
    Fila de tabla de información (datos personales, recepción).
    4 columnas: th(16%=89) | td(34%=189) | th(16%=89) | td(34%=188)
    Con span=True: th(16%=89) | td(84%=466)
    Fuente 7.5 pt para máxima legibilidad.
    """
    FS_LBL = 7.5   # fuente etiqueta (th)
    FS_VAL = 7.5   # fuente valor    (td)
    PAD    = 4     # padding interior

    TH1, TD1 = _I4W[0], _I4W[1]
    TH2, TD2 = _I4W[2], _I4W[3]
    X0, X1, X2, X3 = _I4X

    c.setStrokeColorRGB(*_C_HEAD)
    c.setLineWidth(0.4)

    # th1
    c.setFillColorRGB(*_C_TH)
    c.rect(X0, y - _IH, TH1, _IH, fill=1, stroke=1)
    c.setFillColorRGB(*_C_HEAD)
    c.setFont("Helvetica-Bold", FS_LBL)
    c.drawString(X0 + PAD, y - _IH + PAD, str(l1 or "")[:_chars_for_width(TH1 - PAD * 2, FS_LBL)])

    if span or not l2:
        span_w = TD1 + TH2 + TD2
        c.setFillColorRGB(*_C_WHITE)
        c.rect(X1, y - _IH, span_w, _IH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_BLACK)
        c.setFont("Helvetica", FS_VAL)
        c.drawString(X1 + PAD, y - _IH + PAD, str(v1 or "—")[:_chars_for_width(span_w - PAD * 2, FS_VAL)])
    else:
        # td1
        c.setFillColorRGB(*_C_WHITE)
        c.rect(X1, y - _IH, TD1, _IH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_BLACK)
        c.setFont("Helvetica", FS_VAL)
        c.drawString(X1 + PAD, y - _IH + PAD, str(v1 or "—")[:_chars_for_width(TD1 - PAD * 2, FS_VAL)])
        # th2
        c.setFillColorRGB(*_C_TH)
        c.rect(X2, y - _IH, TH2, _IH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_HEAD)
        c.setFont("Helvetica-Bold", FS_LBL)
        c.drawString(X2 + PAD, y - _IH + PAD, str(l2 or "")[:_chars_for_width(TH2 - PAD * 2, FS_LBL)])
        # td2
        c.setFillColorRGB(*_C_WHITE)
        c.rect(X3, y - _IH, TD2, _IH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_BLACK)
        c.setFont("Helvetica", FS_VAL)
        c.drawString(X3 + PAD, y - _IH + PAD, str(v2 or "—")[:_chars_for_width(TD2 - PAD * 2, FS_VAL)])

    c.setStrokeColorRGB(*_C_BLACK)
    return y - _IH


def _compute_resp_hash(resp: dict) -> str:
    """MD5 del estado del formulario.
    Normaliza FIRMADO_EC:... y data:... a '__sig__' en lugar de excluirlos.
    Esto es crítico: si el campo ESTABA vacío antes de firmar (incluido en hash como '')
    y luego pasa a FIRMADO_EC:... (excluido), el hash cambia y _signed.pdf nunca coincide.
    Con reemplazo: '' → '' y 'FIRMADO_EC:...' → '__sig__' son distintos, pero el hash
    se guarda POST-INSERT (ya con __sig__), y generar_pdf() también ve __sig__ → coinciden."""
    import hashlib as _hl
    _items = []
    for k in sorted(resp):
        v = str(resp.get(k, ''))
        if v.startswith('FIRMADO_EC:') or v.startswith('data:'):
            v = '__sig__'
        _items.append(f"{k}={v}")
    return _hl.md5("|".join(_items).encode("utf-8")).hexdigest()


def _draw_firma_cell(c, y: float,
                     campo: str, sig_coords: dict, page_num: int) -> None:
    """
    Dibuja la celda de firma (siempre vacía) y registra coordenadas para pyHanko.
    El widget PAdES con QR es la única representación visual de la firma.
    """
    y_bot = y - _FRH

    # ── Registrar coordenadas para pyHanko SIEMPRE ──────────
    sig_coords[campo] = (int(_FX1), int(y_bot), int(_FX2), int(y), page_num)

    c.setStrokeColorRGB(*_C_HEAD)
    c.setLineWidth(0.5)

    # Celda siempre vacía — el widget PAdES de pyHanko (QR) es la única
    # representación visual de la firma. Texto dibujado en ReportLab no es
    # verificable y genera conflicto con el widget criptográfico real.
    c.setFillColorRGB(*_C_WHITE)
    c.rect(_FX1, y_bot, _FW, _FRH, fill=1, stroke=1)
    c.setStrokeColorRGB(*_C_PEND)
    c.setLineWidth(0.5)
    cx = _FX1 + _FW / 2
    sign_y = y_bot + _FRH * 0.38
    c.line(_FX1 + 8, sign_y, _FX2 - 8, sign_y)
    c.setFillColorRGB(*_C_PEND)
    c.setFont("Helvetica", 6.5)
    c.drawCentredString(cx, y_bot + _FRH * 0.55, "Firma Electrónica")
    c.setFont("Helvetica", 6.0)
    c.drawCentredString(cx, y_bot + _FRH * 0.42 - 6, "FirmaEC")

    c.setFillColorRGB(*_C_BLACK)
    c.setStrokeColorRGB(*_C_BLACK)
    c.setLineWidth(0.4)


def _firma_row(c, y: float, xs: list, ws: list, cells: list,
               campo: str,
               sig_coords: dict, page_num: int) -> float:
    """
    Dibuja una fila completa de tabla de firmas.
    cells: [(texto, color_fondo), ...] — una tupla por cada columna EXCEPTO la firma.
    El texto se ajusta automáticamente al ancho de la celda con fuente 7.5 pt.
    Nunca desborda el borde de la celda.
    """
    FS   = 7.5    # fuente normal en celdas de datos
    LH   = 10     # interlineado (pts)
    PAD  = 4      # padding horizontal

    y_bot = y - _FRH
    c.setStrokeColorRGB(*_C_HEAD)
    c.setLineWidth(0.4)

    for i, (txt, bg) in enumerate(cells):
        c.setFillColorRGB(*bg)
        c.rect(xs[i], y_bot, ws[i], _FRH, fill=1, stroke=1)
        c.setFillColorRGB(*_C_BLACK)

        s = str(txt or "").strip()
        if not s or s.startswith("data:") or s.startswith("FIRMADO_EC:"):
            continue

        if s in ("SI", "NO", "—"):
            # Valores cortos: centrar vertical y horizontalmente
            col = _C_SI_T if s == "SI" else (_C_NO_T if s == "NO" else _C_PEND)
            c.setFillColorRGB(*col)
            fs_yn = 8.0 if s != "—" else FS
            c.setFont("Helvetica-Bold", fs_yn)
            c.drawCentredString(xs[i] + ws[i] / 2, y_bot + _FRH / 2 - fs_yn / 3, s)
        else:
            # Texto multi-línea — calcular chars máximos según ancho real
            max_ch = _chars_for_width(ws[i] - PAD * 2, FS)
            lines  = _split_text(s, max_ch)
            # Máximas líneas que caben en la fila
            max_lines = max(1, int((_FRH - PAD * 2) / LH))
            lines = lines[:max_lines]

            # Calcular Y de inicio para centrar verticalmente el bloque de texto
            block_h = len(lines) * LH
            ty_start = y_bot + (_FRH + block_h) / 2 - LH + 1

            c.setFont("Helvetica", FS)
            ty = ty_start
            for ln in lines:
                c.drawString(xs[i] + PAD, ty, ln)
                ty -= LH

        c.setFillColorRGB(*_C_BLACK)

    _draw_firma_cell(c, y, campo, sig_coords, page_num)
    c.setStrokeColorRGB(*_C_BLACK)
    return y - _FRH


def _dir_row(c, y: float, texto: str,
             sig_coords: dict, campo: str, page_num: int) -> float:
    """
    Fila de Director/Responsable: celda fusionada del ancho de todas las columnas
    de datos (de _ML a _FX1) + celda de firma a la derecha.
    Fuente 7.5 pt, texto verticalmente centrado.
    """
    FS   = 7.5
    LH   = 10
    PAD  = 4

    y_bot = y - _FRH
    ancho = _FX1 - _ML   # 453 - 20 = 433 pts

    c.setStrokeColorRGB(*_C_HEAD)
    c.setLineWidth(0.4)
    c.setFillColorRGB(*_C_DIRFG)
    c.rect(_ML, y_bot, ancho, _FRH, fill=1, stroke=1)

    # Etiqueta
    c.setFillColorRGB(*_C_HEAD)
    c.setFont("Helvetica-Bold", FS)
    label_y = y - PAD - FS
    c.drawString(_ML + PAD, label_y, "Director/a — Responsable:")

    # Texto del responsable (ajustado al ancho)
    max_ch = _chars_for_width(ancho - PAD * 2, FS)
    lines  = _split_text(texto, max_ch)
    max_ln = max(1, int((_FRH - PAD * 2 - LH * 2) / LH))
    lines  = lines[:max_ln]

    c.setFillColorRGB(*_C_BLACK)
    c.setFont("Helvetica", FS)
    ty = label_y - LH - 1
    for ln in lines:
        c.drawString(_ML + PAD, ty, ln)
        ty -= LH

    _draw_firma_cell(c, y, campo, sig_coords, page_num)
    c.setStrokeColorRGB(*_C_BLACK)
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


# Las versiones mejoradas de _split_text y _draw_page_header están definidas
# arriba (lines ~2160 y ~2196) — no se redefinan aquí.


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

        # Migración de formularios antiguos: garantiza que todos los campos estándar
        # existan en formulario_preguntas antes de generar el PDF.
        _precrear_todas_preguntas(formulario_id, cursor)
        conn.commit()

        # Nota: se permite que no-admin descargue el PDF (necesario para flujo FirmaEC Desktop)
        # El admin puede descargarlo siempre; los demás también, incluso en BORRADOR.

        # Subquery garantiza UNA sola fila por código aunque existan preguntas duplicadas
        # (el duplicado ocurre cuando _precrear_todas_preguntas crea una pregunta nueva
        # para un código que el usuario ya había respondido contra otra pregunta_id anterior).
        # MAX(respuesta) con LEFT JOIN devuelve el valor no-nulo cuando hay un NULL y un valor.
        cursor.execute("""
            SELECT p.codigo,
                   (SELECT rr.respuesta
                      FROM formulario_respuestas rr
                     WHERE rr.pregunta_id = p.id
                       AND rr.formulario_id = %s
                     ORDER BY rr.id DESC
                     LIMIT 1) AS respuesta
              FROM formulario_preguntas p
             WHERE p.formulario_id = %s
        """, (formulario_id, formulario_id))
        # Construimos resp prefiriendo siempre el valor no-vacío ante posibles duplicados de código
        resp = {}
        for _rw in cursor.fetchall():
            if not _rw["codigo"]:
                continue
            _cod = _rw["codigo"]
            _val = _rw["respuesta"] or ""
            if _cod not in resp or (not resp[_cod] and _val):
                resp[_cod] = _val

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

        # _SECMIN = espacio mínimo para arrancar una sección: header + col_header + 2 filas
        # Esto evita headers huérfanos al pie de página sin contenido debajo.
        _SECMIN = _BH + _CH + 2 * _FRH

        def _need(h: float):
            """Salta de página si no hay espacio suficiente para h puntos."""
            if y - h < _MB:
                _npage()

        def _need_dir():
            """
            Antes de una fila de director: asegura que quepan 2 filas.
            Así la fila director nunca queda sola en una página sin la última fila regular.
            """
            if y - 2 * _FRH < _MB:
                _npage()

        def _v(campo: str) -> str:
            val = resp.get(campo, "")
            if not val or val.startswith("data:") or val.startswith("FIRMADO_EC:"):
                return "—"
            return str(val)

        def _yb(val: str):
            if val == "SI": return _C_SI
            if val == "NO": return _C_NO
            return _C_WHITE

        # ─── Título del documento ────────────────────────────────────────────
        _need(38)
        c.setFont("Helvetica-Bold", 13)
        c.setFillColorRGB(*_C_HEAD)
        c.drawCentredString(W / 2, y - 16, "PAZ Y SALVO INSTITUCIONAL")
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(*_C_PEND)
        c.drawCentredString(W / 2, y - 28,
            f"Estado: {formulario.get('estado','—')}  |  Progreso: {formulario.get('porcentaje',0)}%")
        c.setFillColorRGB(*_C_BLACK)
        y -= 38

        # ═══════════════════════════════════════════════════════════════════════
        # 01 — DATOS PERSONALES Y LABORALES
        # ═══════════════════════════════════════════════════════════════════════
        _need(_BH + 6 * _IH + 6)
        y = _sec_header(c, y, "01", "DATOS PERSONALES Y LABORALES", _CS_P)
        y = _info_row(c, y, "NOMBRES Y APELLIDOS", _v("nombres_apellidos"), span=True)
        y = _info_row(c, y, "CÉDULA / PASAPORTE",  _v("cedula"),
                             "MODALIDAD LABORAL",   _v("modalidad"))
        y = _info_row(c, y, "FECHA DE INGRESO",     _v("fecha_ingreso"),
                             "FECHA DE SALIDA",      _v("fecha_salida"))
        _dir_val = " ".join(p for p in [_v("direccion"), _v("numero_domicilio")] if p != "—")
        y = _info_row(c, y, "DIRECCIÓN DOMICILIARIA", _dir_val or "—", span=True)
        y = _info_row(c, y, "PROVINCIA / CANTÓN",
                             f"{_v('provincia')} / {_v('canton')}",
                             "CELULAR / EMERGENCIA",
                             f"{_v('celular')} / {_v('emergencia')}")
        y = _info_row(c, y, "EMAIL PRINCIPAL", _v("email1"),
                             "EMAIL SECUNDARIO", _v("email2"))
        y -= 6

        # ═══════════════════════════════════════════════════════════════════════
        # 02 — DIRECCIÓN / UNIDAD QUE PRESTÓ SUS SERVICIOS
        # ═══════════════════════════════════════════════════════════════════════
        _need(_BH + 3 * _IH + 6)
        y = _sec_header(c, y, "02", "DIRECCIÓN / UNIDAD QUE PRESTÓ SUS SERVICIOS", _CS_U)
        y = _info_row(c, y, "LUGAR DE TRABAJO", _v("lugar_trabajo"),
                             "GRUPO OCUPACIONAL", _v("grupo_ocupacional"))
        y = _info_row(c, y, "DIRECCIÓN / UNIDAD", _v("unidad"), span=True)
        y = _info_row(c, y, "CARGO DESEMPEÑADO",  _v("cargo"),  span=True)
        y -= 6

        # ═══════════════════════════════════════════════════════════════════════
        # 03 — ENTREGA / GESTIÓN DOCUMENTAL Y DE TRÁMITES  (6 columnas)
        # ═══════════════════════════════════════════════════════════════════════
        _need(_SECMIN)
        y = _sec_header(c, y, "03", "ENTREGA / GESTIÓN DOCUMENTAL Y DE TRÁMITES", _CS_T)
        y = _col_header(c, y, _T6X, _T6W, _T6L, _CC_T)

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
            ], cam, sig_coords, pg)

        # Fila condicional: ¿administrador de contrato? (sin firma asociada)
        _admc = resp.get("tramites_admin_contrato", "")
        if _admc and _admc not in ("", "—") and not _admc.startswith("data:") and not _admc.startswith("FIRMADO_EC:"):
            _need(_FRH)
            _admc_txt = f"¿Administrador de contrato?: {_admc}"
            if _admc == "SI":
                _dc_v = _v("tramites_desc_contrato")
                _mm_v = _v("tramites_memo")
                if _dc_v != "—":
                    _admc_txt += f"  |  Descripción del contrato: {_dc_v}"
                if _mm_v != "—":
                    _admc_txt += f"  |  N° Memorando nuevo admin: {_mm_v}"
            _yb_ac = y - _FRH
            c.setStrokeColorRGB(*_C_HEAD)
            c.setLineWidth(0.4)
            c.setFillColorRGB(*_C_WHITE)
            c.rect(_ML, _yb_ac, _CW, _FRH, fill=1, stroke=1)
            c.setFillColorRGB(*_C_BLACK)
            c.setFont("Helvetica", 7.5)
            _max_ac = _chars_for_width(_CW - 8, 7.5)
            _lns_ac = _split_text(_admc_txt, _max_ac)[:max(1, int((_FRH - 8) / 10))]
            _bh_ac  = len(_lns_ac) * 10
            _ty_ac  = _yb_ac + (_FRH + _bh_ac) / 2 - 10 + 1
            for _l_ac in _lns_ac:
                c.drawString(_ML + 4, _ty_ac, _l_ac)
                _ty_ac -= 10
            c.setStrokeColorRGB(*_C_BLACK)
            c.setLineWidth(0.4)
            y -= _FRH

        _need(_FRH)
        _obs_t = _v('tramites_obs')
        jt = (f"Jefe Inmediato: {_v('tramites_jefe_inmediato')}"
              f"  |  Recibe: {_v('tramites_servidor_recibe')}"
              + (f"  |  Obs: {_obs_t}" if _obs_t not in ("", "—") else ""))
        y = _firma_row(c, y, _T6X, _T6W, [
            (jt, _C_WHITE), ("", _C_WHITE), ("", _C_WHITE),
            ("", _C_WHITE), (_v("tramites_nombre_responsable"), _C_WHITE),
        ], "tramites_jefe", sig_coords, pg)
        y -= 6

        # ═══════════════════════════════════════════════════════════════════════
        # 04 — GESTIÓN ADMINISTRATIVA  (5 columnas)
        # ═══════════════════════════════════════════════════════════════════════
        _need(_SECMIN)
        y = _sec_header(c, y, "04", "GESTIÓN ADMINISTRATIVA — DIRECCIÓN ADMINISTRATIVA FINANCIERA", _CS_A)
        y = _col_header(c, y, _T5X, _T5W, _T5L, _CC_A)

        for (desc, yk, dato, nk, cam) in [
            ("Entrega informe fin de gestión",    "admin_informe",
             "—",                                  "admin_nombre_resp1", "admin_r1"),
            ("Entrega bienes muebles y equipos",  "admin_bienes",
             (f"$ {_v('admin_valor_bienes')}"
              + (f"  Acta: {_v('admin_acta_bienes')}"
                 if _v('admin_acta_bienes') not in ("", "—") else "")),
             "admin_nombre_resp2", "admin_r2"),
            ("Valores por deducibles pendientes", "admin_deducibles",
             f"$ {_v('admin_deducibles_valor')}",  "admin_nombre_resp3", "admin_r3"),
            ("Pasajes aéreos por justificar",     "admin_pasajes",
             f"$ {_v('admin_pasajes_valor')}",     "admin_nombre_resp4", "admin_r4"),
        ]:
            _need(_FRH)
            yn = _v(yk)
            y = _firma_row(c, y, _T5X, _T5W, [
                (desc, _C_WHITE), (yn, _yb(yn)), (dato, _C_WHITE), (_v(nk), _C_WHITE),
            ], cam, sig_coords, pg)

        _need_dir()
        y = _dir_row(c, y, _v("admin_responsable"),
                     sig_coords, "admin_dir", pg)
        y -= 6

        # ═══════════════════════════════════════════════════════════════════════
        # 05 — GESTIÓN TIC  (5 columnas)
        # ═══════════════════════════════════════════════════════════════════════
        _need(_SECMIN)
        y = _sec_header(c, y, "05", "GESTIÓN DE TECNOLOGÍAS DE LA INFORMACIÓN Y COMUNICACIÓN", _CS_TIC)
        y = _col_header(c, y, _T5X, _T5W, _T5L, _CC_TIC)

        for (desc, yk, dato, nk, cam) in [
            ("Verificación equipo / IP / accesos",  "tic_verificacion",
             f"IP Fija: {_v('tic_ip_fija')}  Lib: {_v('tic_liberacion')}",
             "tic_nombre_resp1", "tic_r1"),
            ("Entrega backup de información",       "tic_backup",
             f"Ruta: {_v('tic_ruta_backup')}",      "tic_nombre_resp2", "tic_r2"),
            ("Retiro control acceso / contraseñas", "tic_retiro_acceso",
             f"Correo: {_v('tic_cierre_correo')}  eSIGEF: {_v('tic_esigef')}"
             f"  QUIPUX: {_v('tic_quipux')}  SPRYN: {_v('tic_spryn')}  eSByE: {_v('tic_esbye')}",
             "tic_nombre_resp3", "tic_r3"),
            ("Entrega tarjeta acceso / cuentas",   "tic_tarjeta_cuentas",
             f"Obs: {_v('tic_obs')}",
             "tic_nombre_resp4", "tic_r4"),
        ]:
            _need(_FRH)
            yn = _v(yk)
            y = _firma_row(c, y, _T5X, _T5W, [
                (desc, _C_WHITE), (yn, _yb(yn)), (dato, _C_WHITE), (_v(nk), _C_WHITE),
            ], cam, sig_coords, pg)

        _need_dir()
        y = _dir_row(c, y, _v("tic_responsable"),
                     sig_coords, "tic_r5", pg)
        y -= 6

        # ═══════════════════════════════════════════════════════════════════════
        # 06 — GESTIÓN FINANCIERA  (5 columnas)
        # ═══════════════════════════════════════════════════════════════════════
        _need(_SECMIN)
        y = _sec_header(c, y, "06", "GESTIÓN FINANCIERA", _CS_FIN)
        y = _col_header(c, y, _T5X, _T5W, _T5L, _CC_FIN)

        for (desc, yk, dato, nk, cam) in [
            ("Saldos contables pendientes",           "fin_saldos",
             f"$ {_v('fin_saldos_valor')}  {_v('fin_saldos_obs')}",
             "fin_nombre_resp1", "fin_r1"),
            ("Anticipo de sueldos pendiente",         "fin_anticipo",
             f"$ {_v('fin_anticipo_valor')}"
             + (f"  {_v('fin_anticipo_obs')}" if _v('fin_anticipo_obs') not in ("", "—") else ""),
             "fin_nombre_resp2", "fin_r2"),
            ("Recuperación de valores pendiente",     "fin_recuperacion",
             f"$ {_v('fin_recuperacion_valor')}"
             + (f"  {_v('fin_recuperacion_obs')}" if _v('fin_recuperacion_obs') not in ("", "—") else ""),
             "fin_nombre_resp3", "fin_r3"),
            ("Devolución de muebles y equipos",       "fin_devolucion",
             f"$ {_v('fin_devolucion_valor')}"
             + (f"  {_v('fin_devolucion_obs')}" if _v('fin_devolucion_obs') not in ("", "—") else ""),
             "fin_nombre_resp4", "fin_r4"),
        ]:
            _need(_FRH)
            yn = _v(yk)
            y = _firma_row(c, y, _T5X, _T5W, [
                (desc, _C_WHITE), (yn, _yb(yn)), (dato, _C_WHITE), (_v(nk), _C_WHITE),
            ], cam, sig_coords, pg)

        _need_dir()
        y = _dir_row(c, y, _v("fin_director"),
                     sig_coords, "fin_dir", pg)
        y -= 6

        # ═══════════════════════════════════════════════════════════════════════
        # 07 — SEGURIDAD DE LA INFORMACIÓN  (6 columnas)
        # ═══════════════════════════════════════════════════════════════════════
        _need(_SECMIN)
        y = _sec_header(c, y, "07", "SEGURIDAD DE LA INFORMACIÓN — ACUERDO MINISTERIAL 166 (EGSI)", _CS_SEG)
        y = _col_header(c, y, _T6X, _T6W, _T6L, _CC_SEG)

        for (d1, k1, d2, k2, nk, cam) in [
            ("Archivos digitales (EGSI)",          "seg_archivos",
             "Entrega copia de actividades",        "seg_entrega_copia",
             "seg_nombre_resp1", "seg_r1"),
            ("Archivos físicos (Archivo Central)", "seg_archivos_fisicos",
             "Verificación información inst.",      "seg_verificacion_info",
             "seg_nombre_resp2", "seg_r2"),
        ]:
            _need(_FRH)
            yn1 = _v(k1); yn2 = _v(k2)
            y = _firma_row(c, y, _T6X, _T6W, [
                (d1, _C_WHITE), (yn1, _yb(yn1)),
                (d2, _C_WHITE), (yn2, _yb(yn2)),
                (_v(nk), _C_WHITE),
            ], cam, sig_coords, pg)

        _need_dir()
        y = _dir_row(c, y,
                     f"Oficial de Seg.: {_v('seg_oficial')}  |  Responsable: {_v('seg_responsable')}",
                     sig_coords, "seg_oficial", pg)
        y -= 6

        # ═══════════════════════════════════════════════════════════════════════
        # 08 — DIRECCIÓN DE ADMINISTRACIÓN DE RRHH  (5 columnas, 8+1 filas)
        # ═══════════════════════════════════════════════════════════════════════
        _need(_SECMIN)
        y = _sec_header(c, y, "08", "DIRECCIÓN DE ADMINISTRACIÓN DE RECURSOS HUMANOS", _CS_RRHH)
        y = _col_header(c, y, _T5X, _T5W, _T5L, _CC_RRHH)

        for (desc, yk, dato, nk, cam) in [
            ("Capacitación: devengó cursos recibidos",      "rrhh_capacitacion",
             f"Cursos/Eval: {_v('rrhh_cursos_eval')}",      "rrhh_resp_capacitacion",  "rrhh_r1"),
            ("Evaluación del Desempeño aplicada",           "rrhh_evaluacion",
             "—",                                            "rrhh_resp_evaluacion",    "rrhh_r2"),
            ("Viajes al exterior: devengación",             "rrhh_viajes",
             "—",                                            "rrhh_resp_viajes",        "rrhh_r3"),
            ("SIITH: desvinculación del sistema",           "rrhh_siith",
             "—",                                            "rrhh_resp_siith",         "rrhh_r4"),
            ("Declaración juramentada de bienes",           "rrhh_juramentada",
             f"N° Decl: {_v('rrhh_num_declaracion')}",      "rrhh_resp_juramentada",   "rrhh_r6"),
            ("Credencial institucional / Porta cred.",      "rrhh_credencial",
             "—",                                            "rrhh_resp_credencial2",   "rrhh_r7"),
            ("Entrega copia de actividades en CD",          "rrhh_entrega_informe_cd",
             "—",                                            "rrhh_resp_acta",          "rrhh_r8"),
            ("Entrega de ropa de trabajo",                  "rrhh_ropa_trabajo",
             "—",                                            "rrhh_resp_acta",          "rrhh_r8"),
            ("Acta de bienes del custodio",                 "rrhh_acta_bienes",
             "—",                                            "rrhh_resp_acta",          "rrhh_r8"),
        ]:
            _need(_FRH)
            yn = _v(yk) if yk != "—" else "—"
            y = _firma_row(c, y, _T5X, _T5W, [
                (desc, _C_WHITE), (yn, _yb(yn)), (dato, _C_WHITE), (_v(nk), _C_WHITE),
            ], cam, sig_coords, pg)

        # Vacaciones: fila separada con valor en días (badge neutral, igual que en el espejo)
        _need(_FRH)
        _vac_dias = _v("rrhh_vacaciones")
        _vac_val  = f"{_vac_dias} días" if _vac_dias not in ("—", "") else "—"
        y = _firma_row(c, y, _T5X, _T5W, [
            ("Vacaciones acumuladas no gozadas", _C_WHITE),
            (_vac_val,                           _C_WHITE),
            (f"N° Cert: {_v('rrhh_num_certificado')}", _C_WHITE),
            (_v("rrhh_resp_vacaciones"),         _C_WHITE),
        ], "rrhh_r5", sig_coords, pg)

        _need_dir()
        y = _dir_row(c, y, _v("rrhh_director"),
                     sig_coords, "rrhh_dir", pg)
        y -= 6

        # ═══════════════════════════════════════════════════════════════════════
        # 09 — RECEPCIÓN DE DOCUMENTOS
        # ═══════════════════════════════════════════════════════════════════════
        _need(_BH + 2 * _IH + _FRH + 6)
        y = _sec_header(c, y, "09", "RECEPCIÓN DE DOCUMENTOS — DIRECCIÓN DE RRHH", _CS_REC)
        y = _info_row(c, y, "FECHA ENTREGA",         _v("recepcion_fecha"),
                             "N° HOJAS RECIBIDAS",    _v("recepcion_hojas"))
        y = _info_row(c, y, "SERVIDOR/A QUE RECIBE", _v("recepcion_servidor"),
                             "CARGO",                 _v("recepcion_cargo"))
        _need(_FRH)
        y = _firma_row(c, y, _T5X, _T5W, [
            ("Firma Servidor/a que recibe el Paz y Salvo — RRHH", _C_WHITE),
            ("—", _C_WHITE), ("—", _C_WHITE), ("—", _C_WHITE),
        ], "recepcion_r1", sig_coords, pg)
        y -= 6

        # ═══════════════════════════════════════════════════════════════════════
        # 10 — AUTORIZACIÓN — SERVIDOR SALIENTE
        # ═══════════════════════════════════════════════════════════════════════
        LEGAL_H = 80          # caja de texto legal (pts)
        LEGAL_FS = 7.5        # fuente del texto legal
        LEGAL_LH = 10         # interlineado
        LEGAL_MAX = _chars_for_width(_CW - 16, LEGAL_FS)

        _need(_BH + LEGAL_H + _FRH + 10)
        y = _sec_header(c, y, "10", "AUTORIZACIÓN — SERVIDOR SALIENTE (ART. 110 REGLAMENTO LOSEP)", _CS_AUTH)
        legal = (
            "Conforme lo establecido en el artículo 110 del Reglamento a la Ley Orgánica de "
            "Servicio Público (LOSEP), quien suscribe el presente formulario 'PAZ Y SALVO' "
            "AUTORIZA a la DIRECCIÓN ADMINISTRATIVA FINANCIERA del INAMHI para que efectúe "
            "los descuentos detallados en este documento por reintegro y/o recuperación de "
            "valores, bienes y/o especies que se hayan encontrado a su cargo, los mismos que "
            "serán DESCONTADOS a través del rol de pagos y/o liquidación de haberes."
        )
        c.setFillColorRGB(0.97, 0.97, 1.0)
        c.rect(_ML, y - LEGAL_H, _CW, LEGAL_H, fill=1, stroke=1)
        c.setFillColorRGB(*_C_BLACK)
        c.setFont("Helvetica", LEGAL_FS)
        ly = y - 12
        for ln in _split_text(legal, LEGAL_MAX)[:6]:
            c.drawString(_ML + 8, ly, ln)
            ly -= LEGAL_LH
        c.setFont("Helvetica-Bold", LEGAL_FS)
        c.drawString(_ML + 8, ly - 4,
                     f"C.C. DEL FIRMANTE: {_v('cedula_firmante')}"
                     f"   FECHA DE FIRMA: {_v('fecha_firma')}")
        y -= LEGAL_H + 6

        _need(_FRH)
        y = _dir_row(c, y, "FIRMA DE AUTORIZACIÓN — SERVIDOR SALIENTE",
                     sig_coords, "servidor_saliente", pg)

        # Pie de página
        c.setFillColorRGB(*_C_PEND)
        c.setFont("Helvetica", 5.5)
        c.drawCentredString(W / 2, _MB - 8,
            "INAMHI — Formulario Paz y Salvo — Liquidación de Haberes — Versión 2.0 — Quito, Ecuador")
        c.setFillColorRGB(*_C_BLACK)

        c.save()
        with open(json_path, "w", encoding="utf-8") as jf:
            json.dump(sig_coords, jf)

        print(f"[PDF] PDF GENERADO: {filepath}")

        # ── Hash del estado actual: permite detectar PDFs firmados con datos obsoletos ──
        _cur_hash  = _compute_resp_hash(resp)
        _hash_path = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_data.hash")
        try:
            with open(_hash_path, "w", encoding="utf-8") as _hf:
                _hf.write(_cur_hash)
        except Exception:
            pass

        print(f"[PDF] hash_actual={_cur_hash}")

        # ── Prioridad de descarga: _firmaec.pdf → _signed.pdf → PDF fresco ──
        _pdf_firmaec  = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_firmaec.pdf")
        _firmaec_hash = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_firmaec.hash")
        if os.path.exists(_pdf_firmaec) and os.path.exists(_firmaec_hash):
            try:
                with open(_firmaec_hash, encoding="utf-8") as _fhf:
                    _fh = _fhf.read().strip()
                print(f"[PDF] _firmaec.hash={_fh} | coincide={_fh == _cur_hash}")
                if _fh == _cur_hash:
                    print(f"[PDF] PDF DESCARGADO (firmaEC): {_pdf_firmaec}")
                    return send_from_directory(
                        UPLOAD_FOLDER,
                        f"formulario_{formulario_id}_firmaec.pdf",
                        as_attachment=True,
                        download_name=f"PazSalvo_{formulario_id}_firmadoEC.pdf",
                    )
            except Exception as _fhe:
                print(f"[PDF] error leyendo _firmaec.hash: {_fhe}")

        _pdf_signed_dl = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_signed.pdf")
        if os.path.exists(_pdf_signed_dl):
            try:
                from pyhanko.pdf_utils.reader import PdfFileReader as _PdfRdrDL
                with open(_pdf_signed_dl, "rb") as _f_dl:
                    _r_dl = _PdfRdrDL(_f_dl)
                    _n_sigs_dl = len(list(_r_dl.embedded_signatures))
                print(f"[FIRMA] embedded_signatures = {_n_sigs_dl}")
                if _n_sigs_dl > 0:
                    archivo_final = _pdf_signed_dl
                    print(f"[DESCARGA] archivo servido = {archivo_final}")
                    return send_from_directory(
                        UPLOAD_FOLDER,
                        f"formulario_{formulario_id}_signed.pdf",
                        as_attachment=True,
                        download_name=f"PazSalvo_{formulario_id}_firmado.pdf",
                    )
                else:
                    print(f"[DESCARGA] ERROR: _signed.pdf existe pero embedded_signatures=0 — se está enviando el PDF incorrecto")
            except Exception as _she:
                print(f"[DESCARGA] error verificando _signed.pdf: {_she}")

        # PDF fresco — sin firmas digitales
        _fresh_path = os.path.join(UPLOAD_FOLDER, filename)
        print(f"[DESCARGA] archivo servido = {_fresh_path}")
        print(f"[DESCARGA] ADVERTENCIA: PDF sin firmas digitales (no existe _signed.pdf o embedded_signatures=0)")
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

        # Etiquetar _firmaec.pdf con el hash de datos actuales.
        # generar_pdf() solo sirve _firmaec.pdf si este hash coincide con el estado de BD.
        _fec_data_hash_p = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_data.hash")
        _fec_hash_p      = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_firmaec.hash")
        try:
            if os.path.exists(_fec_data_hash_p):
                import shutil as _shu2
                _shu2.copy2(_fec_data_hash_p, _fec_hash_p)
        except Exception as _he:
            print(f"[firmar-ec-desktop] advertencia guardando hash: {_he}")

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
    # Delega completamente a generar_pdf() que ya implementa la lógica completa:
    # hash-check de _firmaec.pdf → _signed.pdf → PDF fresco con datos actualizados.
    return generar_pdf(formulario_id)


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

        cursor.execute("SELECT id, estado, creado_por FROM formularios WHERE id = %s", (formulario_id,))
        formulario = cursor.fetchone()
        if not formulario:
            return jsonify({"mensaje": "Formulario no encontrado"}), 404

        # LEFT JOIN: encontrar la pregunta aunque no tenga asignación explícita
        # (ej. servidor_saliente, recepcion_r1 son auto-firma sin asignación del admin)
        cursor.execute("""
            SELECT p.id AS pregunta_id,
                   a.id AS asignacion_id,
                   a.asignado_usuario_id
            FROM   formulario_preguntas p
            LEFT JOIN formulario_asignaciones a ON p.id = a.pregunta_id
            WHERE  p.formulario_id = %s
              AND  p.codigo        = %s
            LIMIT  1
        """, (formulario_id, campo_firma))
        fila = cursor.fetchone()

        if not fila:
            # La pregunta no existe aún — auto-crearla para que pyHanko pueda firmarla
            cursor.execute("""
                INSERT INTO formulario_preguntas
                (formulario_id, codigo, pregunta, tipo, seccion, opciones, obligatorio, orden)
                VALUES (%s, %s, %s, 'FIRMA', 'AUTORIZACION', NULL, 0, 0)
            """, (formulario_id, campo_firma, campo_firma))
            conn.commit()
            fila = {"pregunta_id": cursor.lastrowid, "asignacion_id": None, "asignado_usuario_id": None}

        # Autorización:
        # · Admin: siempre permitido
        # · Celda con asignación explícita: solo el usuario asignado
        # · Celda sin asignación (servidor_saliente, recepcion_r1, etc.):
        #     permitir si el usuario participa en el formulario o es su creador
        if user["rol"] != "Administrador":
            if fila["asignacion_id"] is not None:
                if fila["asignado_usuario_id"] != user["id"]:
                    return jsonify({
                        "mensaje": (
                            "No tiene autorización para firmar esta celda. "
                            "Solo el usuario designado por el Administrador puede hacerlo."
                        )
                    }), 403
            else:
                cursor.execute("""
                    SELECT 1 FROM formulario_asignaciones
                    WHERE formulario_id = %s AND asignado_usuario_id = %s
                    LIMIT 1
                """, (formulario_id, user["id"]))
                tiene_acceso = cursor.fetchone()
                if not tiene_acceso and formulario.get("creado_por") != user["id"]:
                    return jsonify({
                        "mensaje": "No tiene autorización para firmar esta celda."
                    }), 403

        # Verificar que no esté ya firmada
        cursor.execute("""
            SELECT id FROM formulario_respuestas
            WHERE  formulario_id = %s AND pregunta_id = %s
            LIMIT  1
        """, (formulario_id, fila["pregunta_id"]))
        if cursor.fetchone():
            return jsonify({"mensaje": "Esta celda ya fue firmada y no puede modificarse"}), 400

        # ── Regenerar pdf_orig con TODOS los datos actuales antes de firmar ───
        # Genera siempre un PDF fresco desde BD: mismo contenido que el espejo.
        # _signed.pdf obsoleto (de una firma anterior) se elimina para que pyHanko
        # firme SIEMPRE sobre el PDF recién generado, nunca sobre datos antiguos.
        pdf_orig   = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}.pdf")
        pdf_signed = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_signed.pdf")
        json_path  = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_sigfields.json")

        print(f"[FIRMA] PDF GENERADO (destino): {pdf_orig}")
        print(f"[FIRMA] PDF FIRMADO  (destino): {pdf_signed}")

        try:
            close_db(cursor, conn)
            cursor = conn = None
            generar_pdf(formulario_id)  # escribe pdf_orig, _sigfields.json y _data.hash
            conn   = get_connection()
            cursor = conn.cursor(dictionary=True)
        except Exception as _eg:
            print(f"[firmar-ec] advertencia regenerando pdf_orig: {_eg}")
            if conn is None:
                conn   = get_connection()
                cursor = conn.cursor(dictionary=True)

        _orig_sz = os.path.getsize(pdf_orig) if os.path.exists(pdf_orig) else -1
        print(f"[FIRMA] pdf_orig existe={os.path.exists(pdf_orig)} tamaño={_orig_sz} bytes")

        if not os.path.exists(pdf_orig):
            return jsonify({
                "mensaje": "El PDF no se pudo generar. Use 'Descargar PDF' primero."
            }), 400

        # ── Decidir fuente para firmar: incremental vs. fresco ──────────────────
        # Si _signed.pdf existe y su hash coincide con el _data.hash que generar_pdf()
        # acaba de escribir, significa que los datos del formulario no cambiaron desde
        # la última firma → podemos añadir la nueva firma SOBRE _signed.pdf.
        # Esto acumula firmas PAdES reales (embedded_signatures++) en lugar de resetearlas.
        # Si el hash NO coincide (datos cambiaron), firmamos desde el PDF fresco.
        _use_incremental = False
        _signed_hash_p   = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_signed.hash")
        _data_hash_p     = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_data.hash")

        if os.path.exists(pdf_signed) and os.path.exists(_signed_hash_p) and os.path.exists(_data_hash_p):
            try:
                with open(_signed_hash_p, encoding="utf-8") as _shf:
                    _sh = _shf.read().strip()
                with open(_data_hash_p, encoding="utf-8") as _dhf:
                    _dh = _dhf.read().strip()
                if _sh == _dh:
                    _use_incremental = True
                    print(f"[FIRMA] Firma INCREMENTAL: hash={_sh[:12]}... — añadiendo sobre _signed.pdf")
                else:
                    print(f"[FIRMA] Hash cambió (_signed={_sh[:12]}... vs _data={_dh[:12]}...) — firmando desde cero")
            except Exception as _hc_err:
                print(f"[FIRMA] Error comparando hashes: {_hc_err}")

        if _use_incremental:
            # _pyhanko_firmar lee src_path en memoria antes de escribir dst_path,
            # así que src == dst es seguro cuando ya están en distintas etapas.
            pdf_src = pdf_signed
        else:
            if os.path.exists(pdf_signed):
                try:
                    os.remove(pdf_signed)
                    print(f"[FIRMA] _signed.pdf anterior eliminado (datos desactualizados)")
                except OSError as _rm_err:
                    print(f"[firmar-ec] no se pudo eliminar _signed.pdf: {_rm_err}")
            pdf_src = pdf_orig

        pdf_firmado = pdf_signed
        print(f"[FIRMA] pdf origen = {pdf_src}")
        print(f"[FIRMA] pdf destino = {pdf_firmado}")
        print(f"[FIRMA] Llamando _pyhanko_firmar: src={pdf_src} → dst={pdf_firmado}")

        # ── Firmar con pyHanko ───────────────────────────────────
        try:
            _pyhanko_firmar(
                src_path    = pdf_src,
                dst_path    = pdf_firmado,
                p12_bytes   = p12_bytes,
                password    = password_raw,
                signer_name = signer_name,
                campo_firma = campo_firma,
                json_path   = json_path,
                signer_obj  = _signer_obj,
            )
        except RuntimeError as exc:
            print(f"[FIRMA] ERROR en _pyhanko_firmar: {exc}")
            return jsonify({"mensaje": str(exc)}), 400

        _signed_sz = os.path.getsize(pdf_firmado) if os.path.exists(pdf_firmado) else -1
        print(f"[FIRMA] _pyhanko_firmar completó — _signed.pdf tamaño={_signed_sz} bytes")

        # ── Verificar firmas reales en el PDF producido ──────────
        try:
            from pyhanko.pdf_utils.reader import PdfFileReader as _PdfRdrV
            with open(pdf_firmado, "rb") as _fv2:
                _rv2 = _PdfRdrV(_fv2)
                _n_sigs_v = len(list(_rv2.embedded_signatures))
            print(f"[FIRMA] embedded_signatures = {_n_sigs_v}")
            if _n_sigs_v == 0:
                print("[FIRMA] ERROR: se está enviando el PDF incorrecto — embedded_signatures=0")
            else:
                print(f"[FIRMA] OK: {pdf_firmado} contiene {_n_sigs_v} firma(s) real(es)")
        except Exception as _fve:
            print(f"[FIRMA] advertencia verificando embedded_signatures: {_fve}")

        # ── Guardar resultado en BD ──────────────────────────────
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

        # ── Guardar hash POST-INSERT ──────────────────────────────────────────
        # CRÍTICO: el hash debe calcularse DESPUÉS del INSERT de FIRMADO_EC.
        # Antes del INSERT: campo tramites_r1 = '' (vacío) → hash H1
        # Después del INSERT: campo tramites_r1 = 'FIRMADO_EC:...' → '__sig__' → hash H2
        # H1 ≠ H2 → si guardamos H1 como _signed.hash, nunca coincidirá con H2 al descargar.
        # Solución: guardamos H2 como _signed.hash para que coincida con la próxima llamada
        # a generar_pdf() que también verá tramites_r1=FIRMADO_EC:... → '__sig__' → H2.
        try:
            cursor.execute("""
                SELECT p.codigo,
                       (SELECT rr.respuesta
                          FROM formulario_respuestas rr
                         WHERE rr.pregunta_id = p.id
                           AND rr.formulario_id = %s
                         ORDER BY rr.id DESC
                         LIMIT 1) AS respuesta
                  FROM formulario_preguntas p
                 WHERE p.formulario_id = %s
            """, (formulario_id, formulario_id))
            _resp_post = {}
            for _rw in cursor.fetchall():
                if not _rw["codigo"]:
                    continue
                _cod = _rw["codigo"]
                _val = _rw["respuesta"] or ""
                if _cod not in _resp_post or (not _resp_post[_cod] and _val):
                    _resp_post[_cod] = _val
            _post_hash = _compute_resp_hash(_resp_post)

            _signed_hash_p = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_signed.hash")
            _data_hash_p   = os.path.join(UPLOAD_FOLDER, f"formulario_{formulario_id}_data.hash")
            with open(_signed_hash_p, "w", encoding="utf-8") as _hf:
                _hf.write(_post_hash)
            with open(_data_hash_p, "w", encoding="utf-8") as _hf:
                _hf.write(_post_hash)
            print(f"[FIRMA] hash post-INSERT guardado: {_post_hash}")
        except Exception as _ph_err:
            print(f"[FIRMA] advertencia guardando hash post-INSERT: {_ph_err}")

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
        print("[ERROR /firmar-ec]", traceback.format_exc())
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
    signer_obj=None,
) -> None:
    """
    Firma digitalmente la celda `campo_firma` del PDF con pyHanko (PAdES).
    Genera una firma criptográfica real (/Sig + ByteRange + /Contents PKCS#7)
    reconocida por FirmaEC 5.x.  Valida que el PDF resultante contenga la firma
    antes de escribirlo a disco — nunca entrega un PDF sin firma válida.
    """
    import io as _io
    import asyncio as _aio

    try:
        from pyhanko.sign import signers, fields as sign_fields
        from pyhanko.sign.signers.pdf_signer import PdfSigner, PdfSignatureMetadata
        from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
        from pyhanko.pdf_utils.reader import PdfFileReader as _PdfRdr
    except ImportError:
        raise RuntimeError(
            "pyHanko no está instalado. Ejecute: pip install pyhanko pyhanko-certvalidator"
        )

    # ── Cargar firmante PKCS#12 ──────────────────────────────────
    if signer_obj is not None:
        signer = signer_obj
    else:
        import tempfile as _tf2
        signer = None
        _tmp2  = None
        try:
            with _tf2.NamedTemporaryFile(suffix='.p12', delete=False) as _t:
                _t.write(p12_bytes)
                _tmp2 = _t.name
            for _enc in ('utf-8', 'latin-1', 'cp1252', 'utf-16-le'):
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
                try:
                    os.unlink(_tmp2)
                except Exception:
                    pass
        if signer is None:
            raise RuntimeError(
                "No se pudo cargar el certificado. Verifique contraseña y que el .p12 sea válido."
            )

    # ── Leer coordenadas de celdas ──────────────────────────────
    try:
        with open(json_path, "r", encoding="utf-8") as jf:
            sig_map = json.load(jf)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"No se pudo leer el mapa de coordenadas: {exc}")

    if campo_firma not in sig_map:
        try:
            with open(src_path, "rb") as _fb:
                _last_page = max(0, _PdfRdr(_fb).get_num_pages() - 1)
        except Exception:
            _last_page = 0
        sig_map[campo_firma] = (395, 50, 555, 130, _last_page)
        print(f"[pyhanko] Fallback coords para '{campo_firma}': página {_last_page}")

    coords   = sig_map[campo_firma]
    SIG_BOX  = (int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3]))
    SIG_PAGE = int(coords[4])

    # ── Apariencia visual (QRStampStyle con fallback a texto simple) ─
    qr_url      = "https://validar.firmaec.ec"
    nombre_disp = (signer_name[:60] if len(signer_name) > 60 else signer_name)
    stamp_style = None
    try:
        from pyhanko.stamp import QRStampStyle
        from pyhanko.stamp.text import TextBoxStyle
        stamp_style = QRStampStyle(
            stamp_text=(
                "Validar en FirmaEC.\n"
                "Firmado por:\n%(signer)s"
            ),
            text_box_style=TextBoxStyle(font_size=8, text_color=(0.0, 0.12, 0.51)),
            background_opacity=1.0,
            border_width=1,
        )
    except Exception as e:
        print("[QR] appearance failed:", e)
        print(f"[pyhanko] QRStampStyle no disponible; usando apariencia por defecto")
    print("[QR] stamp_style =", stamp_style)

    # ── Subfiltro PAdES: ETSI.CAdES.detached (FirmaEC 5.x requiere CAdES, no PKCS7) ──
    # En pyHanko 0.35.1 el enum SigSeedSubFilter tiene TRES miembros:
    #   ADOBE_PKCS7_DETACHED = NameObject('/adbe.pkcs7.detached')  ← default del sistema
    #   PADES               = NameObject('/ETSI.CAdES.detached')   ← LO QUE FIRMAEC REQUIERE
    #   ETSI_RFC3161        = NameObject('/ETSI.RFC3161')
    # El miembro se llama PADES (no ETSI_CADES_DETACHED).
    # sign_fields ya importado arriba como: from pyhanko.sign import fields as sign_fields
    _subfilter = sign_fields.SigSeedSubFilter.PADES
    print(f"[pyhanko] SubFilter forzado: {_subfilter.name} = {_subfilter.value}")

    FIELD_NAME = f"Sig_{campo_firma}"

    # ── Leer PDF fuente en memoria para escritura incremental ────
    with open(src_path, "rb") as _f_src:
        src_bytes = _f_src.read()
    in_stream = _io.BytesIO(src_bytes)

    # ── Construir writer + campo de firma + firmar ───────────────
    out_buf = _io.BytesIO()
    try:
        writer = IncrementalPdfFileWriter(in_stream)

        # Crear el campo de firma en la posición exacta de la celda
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
            subfilter  = _subfilter,
        )

        pdf_signer_obj = PdfSigner(
            meta, signer,
            **({"stamp_style": stamp_style} if stamp_style is not None else {}),
        )

        # existing_fields_only=True: el campo ya fue creado con append_signature_field
        _sign_kw = dict(
            existing_fields_only = True,
            output               = out_buf,
        )
        if stamp_style is not None:
            _sign_kw['appearance_text_params'] = {'url': qr_url, 'signer': nombre_disp}

        # Invocar sign_pdf de forma compatible con versiones sync y async de pyHanko.
        # En Flask sincrónico no hay event loop activo en el thread → asyncio.run() es seguro.
        _result = pdf_signer_obj.sign_pdf(writer, **_sign_kw)
        if _aio.iscoroutine(_result):
            # pyHanko >= 0.15.0: sign_pdf es async; asyncio.run() crea un loop nuevo en este thread
            _aio.run(_result)
        print("[QR] appearance generated")

    except Exception as _sign_err:
        raise RuntimeError(
            f"pyHanko sign_pdf falló: {type(_sign_err).__name__}: {_sign_err}"
        )

    # ── Verificar que out_buf tiene contenido antes de escribir ──
    _signed_bytes = out_buf.getvalue()
    if len(_signed_bytes) < 1024:
        raise RuntimeError(
            f"pyHanko produjo un PDF de {len(_signed_bytes)} bytes — "
            "demasiado pequeño para ser válido. La firma no se aplicó correctamente."
        )

    # ── Escribir a disco ─────────────────────────────────────────
    with open(dst_path, "wb") as f_out:
        f_out.write(_signed_bytes)

    # ── Inspección estructural del PDF firmado ──────────────────────────────
    # Verifica /AcroForm, /Sig, /ByteRange, SubFilter y embedded_signatures.
    # Si no hay firmas reales: borra el archivo y lanza RuntimeError
    # (el sistema NUNCA entrega un PDF sin firma criptográfica válida).
    print(f"[pyhanko] Inspeccionando PDF firmado: {dst_path}")
    try:
        with open(dst_path, "rb") as _fv:
            _rv   = _PdfRdr(_fv)
            _sigs = list(_rv.embedded_signatures)

        print(f"[pyhanko] embedded_signatures count: {len(_sigs)}")
        print("[PDF] embedded_signatures =", len(_sigs))
        for _idx, _s in enumerate(_sigs):
            try:
                _so   = _s.sig_object
                _sf   = str(_so.get('/SubFilter', 'N/A'))
                _br   = _so.get('/ByteRange')
                _ct   = _so.get('/Contents')
                _name = str(_so.get('/Name', 'N/A'))
                _loc  = str(_so.get('/Location', 'N/A'))
                print(f"[pyhanko]  Firma[{_idx}]  campo={_s.field_name}")
                print(f"[pyhanko]           SubFilter={_sf}")
                print(f"[pyhanko]           ByteRange={bool(_br)} /Contents={bool(_ct)}")
                print(f"[pyhanko]           Name={_name}  Location={_loc}")
                # Detectar perfil de firma
                if 'ETSI.CAdES.detached' in _sf:
                    print(f"[pyhanko]           Perfil: PAdES CAdES-DETACHED ✓ (compatible FirmaEC)")
                elif 'adbe.pkcs7.detached' in _sf:
                    print(f"[pyhanko]           Perfil: Adobe PKCS7-DETACHED ⚠ (Adobe sí, FirmaEC puede no reconocer)")
                elif 'adbe.pkcs7.sha1' in _sf:
                    print(f"[pyhanko]           Perfil: Adobe PKCS7-SHA1 ✗ (obsoleto, FirmaEC no reconoce)")
                else:
                    print(f"[pyhanko]           Perfil: DESCONOCIDO — verificar compatibilidad FirmaEC")
            except Exception as _si:
                print(f"[pyhanko]  Firma[{_idx}] error inspeccionando: {_si}")

        if not _sigs:
            os.remove(dst_path)
            raise RuntimeError(
                "pyHanko escribió el PDF PERO embedded_signatures=0. "
                "El PDF NO contiene /Sig + ByteRange reales. "
                "FirmaEC mostraría 'Documento sin firmas'. PDF rechazado."
            )

        # Inspección raw del byte stream para confirmar /ByteRange
        with open(dst_path, "rb") as _fbr:
            _raw = _fbr.read()
        _has_byterange = b'/ByteRange' in _raw
        _has_contents  = b'/Contents' in _raw
        _has_acroform  = b'/AcroForm' in _raw
        _has_sig_type  = b'/Sig' in _raw
        print(f"[pyhanko] Inspección raw → /AcroForm={_has_acroform} /Sig={_has_sig_type} /ByteRange={_has_byterange} /Contents={_has_contents}")

        if not _has_byterange:
            os.remove(dst_path)
            raise RuntimeError(
                "El PDF firmado no contiene /ByteRange en el stream. "
                "La firma PAdES es inválida. PDF rechazado."
            )

    except RuntimeError:
        raise
    except Exception as _ve:
        print(f"[pyhanko] Advertencia inspeccionando firma: {_ve}")


if __name__ == "__main__":
    app.run(debug=False, port=5000, threaded=True, use_reloader=False)