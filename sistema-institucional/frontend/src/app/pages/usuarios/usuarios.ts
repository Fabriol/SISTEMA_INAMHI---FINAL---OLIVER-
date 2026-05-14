import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { UsuariosService } from '../../core/services/usuarios.service';
import Swal from 'sweetalert2';

@Component({
  selector: 'app-usuarios',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './usuarios.html',
  styleUrl: './usuarios.scss'
})
export class Usuarios implements OnInit {

  usuarios: any[] = [];
  roles: any[] = [];
  usuarioActual: any = {};
  filtro = '';
  cargando = false;

  nuevo: any = this.formVacio();
  mostrarModal = false;
  usuarioEditando: any = null;

  private alertaActiva = false;

  constructor(private usuariosService: UsuariosService) {}

  ngOnInit(): void {
    this.usuarioActual = JSON.parse(localStorage.getItem('usuario') || '{}');
    this.cargarUsuarios();
    this.cargarRoles();
  }

  formVacio(): any {
    return {
      nombres: '',
      apellidos: '',
      usuario: '',
      password: '',
      rol: '',
      estado: 'ACTIVO'
    };
  }

  alertaRapida(titulo: string, texto: string): void {
    if (this.alertaActiva) return;

    this.alertaActiva = true;

    Swal.fire({
      icon: 'error',
      title: titulo,
      text: texto,
      timer: 1300,
      showConfirmButton: false
    }).then(() => {
      this.alertaActiva = false;
    });
  }

  campoSoloLetrasValido(texto: string): boolean {
    return /^[a-zA-ZÁÉÍÓÚáéíóúÑñ\s]+$/.test(texto || '');
  }

  campoUsuarioValido(texto: string): boolean {
    return /^[a-z0-9._-]+$/.test(texto || '');
  }

  validarSoloLetras(event: any, objeto: any, campo: string): void {
    const valor = event.target.value;

    if (/[^a-zA-ZÁÉÍÓÚáéíóúÑñ\s]/.test(valor)) {
      this.alertaRapida('Solo letras', 'No puedes ingresar números ni símbolos.');
    }

    objeto[campo] = valor;
  }

  validarSoloNumeros(event: any, objeto: any, campo: string): void {
    const valor = event.target.value;

    if (/[^0-9]/.test(valor)) {
      this.alertaRapida('Solo números', 'No puedes ingresar letras ni símbolos.');
    }

    objeto[campo] = valor;
  }

  soloUsuario(event: any, objeto: any): void {
    const valor = event.target.value.toLowerCase();

    if (/[^a-zA-Z0-9._-]/.test(valor)) {
      this.alertaRapida(
        'Usuario inválido',
        'Solo se permiten letras, números, punto, guion y guion bajo.'
      );
    }

    objeto.usuario = valor
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '');
  }

  onNombreApellidoNuevo(event: any, campo: 'nombres' | 'apellidos'): void {
    this.validarSoloLetras(event, this.nuevo, campo);

    if (
      this.campoSoloLetrasValido(this.nuevo.nombres) &&
      this.campoSoloLetrasValido(this.nuevo.apellidos)
    ) {
      this.generarUsuario();
    }
  }

  onNombreApellidoEditar(event: any, campo: 'nombres' | 'apellidos'): void {
    this.validarSoloLetras(event, this.usuarioEditando, campo);
  }

  generarUsuario(): void {
    const nombres = this.normalizarUsuario(this.nuevo.nombres || '');
    const apellidos = this.normalizarUsuario(this.nuevo.apellidos || '');

    if (!nombres || !apellidos) {
      this.nuevo.usuario = '';
      return;
    }

    this.nuevo.usuario = nombres.charAt(0) + apellidos.replace(/\s/g, '');
  }

  normalizarUsuario(texto: string): string {
    return texto
      .trim()
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/ñ/g, 'n')
      .replace(/[^a-z\s]/g, '')
      .replace(/\s+/g, ' ');
  }

  limpiarTexto(texto: string): string {
    return (texto || '').trim().replace(/\s+/g, ' ');
  }

  esAdmin(): boolean {
    return this.usuarioActual?.rol === 'Administrador';
  }

  puedeEditar(): boolean {
    return ['Administrador', 'Talento Humano - Recepcion Documentos']
      .includes(this.usuarioActual?.rol);
  }

  puedeEliminar(): boolean {
    return this.usuarioActual?.rol === 'Administrador';
  }

  get usuariosFiltrados(): any[] {
    const texto = this.filtro.toLowerCase().trim();

    if (!texto) return this.usuarios;

    return this.usuarios.filter((u: any) =>
      `${u.nombres} ${u.apellidos} ${u.usuario} ${u.rol} ${u.estado}`
        .toLowerCase()
        .includes(texto)
    );
  }

  validarNuevo(): boolean {
    this.nuevo.nombres = this.limpiarTexto(this.nuevo.nombres);
    this.nuevo.apellidos = this.limpiarTexto(this.nuevo.apellidos);

    if (!this.nuevo.nombres || !this.nuevo.apellidos || !this.nuevo.password || !this.nuevo.rol) {
      Swal.fire('Campos incompletos', 'Complete nombres, apellidos, contraseña y rol.', 'warning');
      return false;
    }

    if (!this.campoSoloLetrasValido(this.nuevo.nombres)) {
      Swal.fire('Error', 'El campo nombres solo permite letras. Corrige el valor.', 'error');
      return false;
    }

    if (!this.campoSoloLetrasValido(this.nuevo.apellidos)) {
      Swal.fire('Error', 'El campo apellidos solo permite letras. Corrige el valor.', 'error');
      return false;
    }

    if (this.nuevo.nombres.length < 2 || this.nuevo.apellidos.length < 2) {
      Swal.fire('Validación', 'Nombres y apellidos deben tener mínimo 2 letras.', 'warning');
      return false;
    }

    this.generarUsuario();

    if (!this.campoUsuarioValido(this.nuevo.usuario)) {
      Swal.fire('Error', 'El usuario contiene caracteres inválidos.', 'error');
      return false;
    }

    if (this.nuevo.password.length < 4) {
      Swal.fire('Validación', 'La contraseña debe tener mínimo 4 caracteres.', 'warning');
      return false;
    }

    return true;
  }

  validarEdicion(): boolean {
    this.usuarioEditando.nombres = this.limpiarTexto(this.usuarioEditando.nombres);
    this.usuarioEditando.apellidos = this.limpiarTexto(this.usuarioEditando.apellidos);

    if (!this.usuarioEditando.nombres || !this.usuarioEditando.apellidos || !this.usuarioEditando.rol) {
      Swal.fire('Campos incompletos', 'Complete nombres, apellidos y rol.', 'warning');
      return false;
    }

    if (!this.campoSoloLetrasValido(this.usuarioEditando.nombres)) {
      Swal.fire('Error', 'El campo nombres solo permite letras.', 'error');
      return false;
    }

    if (!this.campoSoloLetrasValido(this.usuarioEditando.apellidos)) {
      Swal.fire('Error', 'El campo apellidos solo permite letras.', 'error');
      return false;
    }

    if (!this.campoUsuarioValido(this.usuarioEditando.usuario)) {
      Swal.fire('Error', 'El usuario contiene caracteres inválidos.', 'error');
      return false;
    }

    if (this.usuarioEditando.password && this.usuarioEditando.password.length < 4) {
      Swal.fire('Validación', 'La nueva contraseña debe tener mínimo 4 caracteres.', 'warning');
      return false;
    }

    return true;
  }

  cargarUsuarios(): void {
    this.usuariosService.listar().subscribe({
      next: (data: any) => this.usuarios = data,
      error: (err: any) => Swal.fire('Error', err.error?.mensaje || 'Error al cargar usuarios', 'error')
    });
  }

  cargarRoles(): void {
    this.usuariosService.roles().subscribe({
      next: (data: any) => this.roles = data,
      error: () => this.roles = []
    });
  }

  guardar(): void {
    if (!this.esAdmin()) {
      Swal.fire('Sin permisos', 'Solo el Administrador puede crear usuarios.', 'warning');
      return;
    }

    if (!this.validarNuevo()) return;

    this.cargando = true;

    this.usuariosService.crear(this.nuevo).subscribe({
      next: () => {
        this.cargando = false;
        Swal.fire('Creado', 'Usuario creado correctamente.', 'success');
        this.limpiar();
        this.cargarUsuarios();
      },
      error: (err: any) => {
        this.cargando = false;
        Swal.fire('Error', err.error?.mensaje || 'Error al guardar usuario', 'error');
      }
    });
  }

  limpiar(): void {
    this.nuevo = this.formVacio();
  }

  abrirEditar(u: any): void {
    if (!this.puedeEditar()) {
      Swal.fire('Sin permisos', 'No puedes editar usuarios.', 'warning');
      return;
    }

    this.usuarioEditando = { ...u, password: '' };
    this.mostrarModal = true;
  }

  cerrarModal(): void {
    this.mostrarModal = false;
    this.usuarioEditando = null;
  }

  guardarEdicion(): void {
    if (!this.validarEdicion()) return;

    this.usuariosService.actualizar(this.usuarioEditando.id, this.usuarioEditando).subscribe({
      next: () => {
        Swal.fire('Actualizado', 'Usuario actualizado correctamente.', 'success');
        this.cerrarModal();
        this.cargarUsuarios();
      },
      error: (err: any) => Swal.fire('Error', err.error?.mensaje || 'Error al actualizar usuario', 'error')
    });
  }

  cambiarEstado(u: any): void {
    if (!this.esAdmin()) {
      Swal.fire('Sin permisos', 'Solo el Administrador puede cambiar estados.', 'warning');
      return;
    }

    const nuevoEstado = u.estado === 'ACTIVO' ? 'INHABILITADO' : 'ACTIVO';

    Swal.fire({
      title: `¿Cambiar a ${nuevoEstado}?`,
      icon: 'question',
      showCancelButton: true,
      confirmButtonText: 'Sí, cambiar',
      cancelButtonText: 'Cancelar'
    }).then((result) => {
      if (result.isConfirmed) {
        this.usuariosService.cambiarEstado(u.id, nuevoEstado).subscribe({
          next: () => {
            Swal.fire('Actualizado', `Usuario cambiado a ${nuevoEstado}.`, 'success');
            this.cargarUsuarios();
          },
          error: (err: any) => Swal.fire('Error', err.error?.mensaje || 'Error al cambiar estado', 'error')
        });
      }
    });
  }

  eliminar(id: number): void {
    if (!this.puedeEliminar()) {
      Swal.fire('Sin permisos', 'Solo el Administrador puede eliminar usuarios.', 'warning');
      return;
    }

    Swal.fire({
      title: '¿Eliminar usuario?',
      text: 'Esta acción no se puede deshacer.',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: 'Sí, eliminar',
      cancelButtonText: 'Cancelar',
      confirmButtonColor: '#dc2626'
    }).then((result) => {
      if (result.isConfirmed) {
        this.usuariosService.eliminar(id).subscribe({
          next: () => {
            Swal.fire('Eliminado', 'Usuario eliminado correctamente.', 'success');
            this.cargarUsuarios();
          },
          error: (err: any) => Swal.fire('Error', err.error?.mensaje || 'Error al eliminar', 'error')
        });
      }
    });
  }
}