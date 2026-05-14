from flask import Blueprint, request, jsonify
from database import get_connection

usuarios_bp = Blueprint('usuarios', __name__)

@usuarios_bp.route('/api/usuarios', methods=['GET'])
def get_usuarios():
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM usuarios")
    data = cursor.fetchall()

    return jsonify(data)


@usuarios_bp.route('/api/usuarios', methods=['POST'])
def crear_usuario():
    data = request.json

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO usuarios (nombres, email, password, rol)
        VALUES (%s, %s, %s, %s)
    """, (
        data['nombres'],
        data['email'],
        data['password'],
        data['rol']
    ))

    conn.commit()

    return jsonify({"mensaje": "Usuario creado"})


@usuarios_bp.route('/api/usuarios/<int:id>', methods=['DELETE'])
def eliminar_usuario(id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM usuarios WHERE id = %s", (id,))
    conn.commit()

    return jsonify({"mensaje": "Eliminado"})