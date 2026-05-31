import { Component, OnInit, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { forkJoin } from 'rxjs';
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

  constructor(
    private usuariosService: UsuariosService,
    private cdr: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    this.usuarioActual = JSON.parse(localStorage.getItem('usuario') || '{}');
    this.cargarDatosIniciales();
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

  cargarDatosIniciales(): void {
    this.cargando = true;

    forkJoin({
      usuarios: this.usuariosService.listar(),
      roles: this.usuariosService.roles()
    }).subscribe({
      next: (res: any) => {
        this.usuarios = res.usuarios || [];
        this.roles = res.roles || [];
        this.cargando = false;
        this.cdr.detectChanges();
      },
      error: (err: any) => {
        this.usuarios = [];
        this.roles = [];
        this.cargando = false;
        Swal.fire('Error', err.error?.mensaje || 'Error al cargar información', 'error');
        this.cdr.detectChanges();
      }
    });
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
    return /^[a-zA-ZÁÉÍÓÚáéíóúÑñ\s]+$/.test((texto || '').trim());
  }

  campoUsuarioValido(texto: string): boolean {
    return /^[a-z0-9._-]+$/.test(texto || '');
  }

  // ── Getters de estado para mostrar errores en tiempo real ──
  get errNombresNuevo(): string {
    const v = (this.nuevo.nombres || '').trim();
    if (!v) return 'Obligatorio';
    if (v.length < 2) return 'Mínimo 2 caracteres';
    if (v.length > 50) return 'Máximo 50 caracteres';
    if (!this.campoSoloLetrasValido(v)) return 'Solo letras y espacios';
    return '';
  }

  get errApellidosNuevo(): string {
    const v = (this.nuevo.apellidos || '').trim();
    if (!v) return 'Obligatorio';
    if (v.length < 2) return 'Mínimo 2 caracteres';
    if (v.length > 50) return 'Máximo 50 caracteres';
    if (!this.campoSoloLetrasValido(v)) return 'Solo letras y espacios';
    return '';
  }

  get errPasswordNuevo(): string {
    const v = this.nuevo.password || '';
    if (!v) return 'Obligatorio';
    if (v.length < 6) return 'Mínimo 6 caracteres';
    if (v.length > 50) return 'Máximo 50 caracteres';
    return '';
  }

  get errRolNuevo(): string {
    return !this.nuevo.rol ? 'Seleccione un rol' : '';
  }

  get errNombresEditar(): string {
    const v = (this.usuarioEditando?.nombres || '').trim();
    if (!v) return 'Obligatorio';
    if (v.length < 2) return 'Mínimo 2 caracteres';
    if (v.length > 50) return 'Máximo 50 caracteres';
    if (!this.campoSoloLetrasValido(v)) return 'Solo letras y espacios';
    return '';
  }

  get errApellidosEditar(): string {
    const v = (this.usuarioEditando?.apellidos || '').trim();
    if (!v) return 'Obligatorio';
    if (v.length < 2) return 'Mínimo 2 caracteres';
    if (v.length > 50) return 'Máximo 50 caracteres';
    if (!this.campoSoloLetrasValido(v)) return 'Solo letras y espacios';
    return '';
  }

  get errPasswordEditar(): string {
    const v = this.usuarioEditando?.password || '';
    if (!v) return ''; // opcional en edición
    if (v.length < 6) return 'Mínimo 6 caracteres';
    if (v.length > 50) return 'Máximo 50 caracteres';
    return '';
  }

  get errRolEditar(): string {
    return !this.usuarioEditando?.rol ? 'Seleccione un rol' : '';
  }

  get formularioNuevoValido(): boolean {
    return (
      !this.errNombresNuevo &&
      !this.errApellidosNuevo &&
      !this.errPasswordNuevo &&
      !this.errRolNuevo &&
      !!this.nuevo.nombres?.trim() &&
      !!this.nuevo.apellidos?.trim()
    );
  }

  get formularioEditarValido(): boolean {
    return (
      !this.errNombresEditar &&
      !this.errApellidosEditar &&
      !this.errPasswordEditar &&
      !this.errRolEditar
    );
  }

  validarSoloLetras(event: any, objeto: any, campo: string): void {
    const valor = event.target.value;

    if (/[^a-zA-ZÁÉÍÓÚáéíóúÑñ\s]/.test(valor)) {
      this.alertaRapida('Solo letras', 'No puedes ingresar números ni símbolos.');
    }

    objeto[campo] = valor;
  }

  soloUsuario(event: any, objeto: any): void {
    const valor = event.target.value.toLowerCase();

    if (/[^a-zA-Z0-9._-]/.test(valor)) {
      this.alertaRapida('Usuario inválido', 'Solo letras, números, punto, guion y guion bajo.');
    }

    objeto.usuario = valor.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
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

    if (
      this.campoSoloLetrasValido(this.usuarioEditando.nombres) &&
      this.campoSoloLetrasValido(this.usuarioEditando.apellidos)
    ) {
      this.generarUsuarioEditar();
    }
  }

  generarUsuario(): void {
    const nombres = this.normalizarUsuario(this.nuevo.nombres || '');
    const apellidos = this.normalizarUsuario(this.nuevo.apellidos || '');

    this.nuevo.usuario = nombres && apellidos
      ? nombres.charAt(0) + apellidos.replace(/\s/g, '')
      : '';
  }

  generarUsuarioEditar(): void {
    const nombres = this.normalizarUsuario(this.usuarioEditando?.nombres || '');
    const apellidos = this.normalizarUsuario(this.usuarioEditando?.apellidos || '');

    this.usuarioEditando.usuario = nombres && apellidos
      ? nombres.charAt(0) + apellidos.replace(/\s/g, '')
      : '';
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

    if (!this.nuevo.nombres) {
      Swal.fire('Campos incompletos', 'Ingrese los nombres del usuario.', 'warning');
      return false;
    }
    if (this.nuevo.nombres.length < 2) {
      Swal.fire('Validación', 'Nombres: mínimo 2 caracteres.', 'warning');
      return false;
    }
    if (this.nuevo.nombres.length > 50) {
      Swal.fire('Validación', 'Nombres: máximo 50 caracteres.', 'warning');
      return false;
    }
    if (!this.campoSoloLetrasValido(this.nuevo.nombres)) {
      Swal.fire('Validación', 'Nombres: solo se permiten letras y espacios.', 'error');
      return false;
    }

    if (!this.nuevo.apellidos) {
      Swal.fire('Campos incompletos', 'Ingrese los apellidos del usuario.', 'warning');
      return false;
    }
    if (this.nuevo.apellidos.length < 2) {
      Swal.fire('Validación', 'Apellidos: mínimo 2 caracteres.', 'warning');
      return false;
    }
    if (this.nuevo.apellidos.length > 50) {
      Swal.fire('Validación', 'Apellidos: máximo 50 caracteres.', 'warning');
      return false;
    }
    if (!this.campoSoloLetrasValido(this.nuevo.apellidos)) {
      Swal.fire('Validación', 'Apellidos: solo se permiten letras y espacios.', 'error');
      return false;
    }

    this.generarUsuario();

    if (!this.nuevo.usuario || !this.campoUsuarioValido(this.nuevo.usuario)) {
      Swal.fire('Validación', 'Usuario inválido. Solo letras minúsculas, números, punto, guion y guion bajo.', 'error');
      return false;
    }
    if (this.nuevo.usuario.length > 30) {
      Swal.fire('Validación', 'Usuario: máximo 30 caracteres.', 'warning');
      return false;
    }

    if (!this.nuevo.password) {
      Swal.fire('Campos incompletos', 'Ingrese una contraseña.', 'warning');
      return false;
    }
    if (this.nuevo.password.length < 6) {
      Swal.fire('Validación', 'La contraseña debe tener mínimo 6 caracteres.', 'warning');
      return false;
    }
    if (this.nuevo.password.length > 50) {
      Swal.fire('Validación', 'La contraseña no debe superar 50 caracteres.', 'warning');
      return false;
    }

    if (!this.nuevo.rol) {
      Swal.fire('Campos incompletos', 'Seleccione un rol para el usuario.', 'warning');
      return false;
    }

    return true;
  }

  validarEdicion(): boolean {
    this.usuarioEditando.nombres = this.limpiarTexto(this.usuarioEditando.nombres);
    this.usuarioEditando.apellidos = this.limpiarTexto(this.usuarioEditando.apellidos);

    if (!this.usuarioEditando.nombres) {
      Swal.fire('Campos incompletos', 'Ingrese los nombres del usuario.', 'warning');
      return false;
    }
    if (this.usuarioEditando.nombres.length < 2) {
      Swal.fire('Validación', 'Nombres: mínimo 2 caracteres.', 'warning');
      return false;
    }
    if (this.usuarioEditando.nombres.length > 50) {
      Swal.fire('Validación', 'Nombres: máximo 50 caracteres.', 'warning');
      return false;
    }
    if (!this.campoSoloLetrasValido(this.usuarioEditando.nombres)) {
      Swal.fire('Validación', 'Nombres: solo se permiten letras y espacios.', 'error');
      return false;
    }

    if (!this.usuarioEditando.apellidos) {
      Swal.fire('Campos incompletos', 'Ingrese los apellidos del usuario.', 'warning');
      return false;
    }
    if (this.usuarioEditando.apellidos.length < 2) {
      Swal.fire('Validación', 'Apellidos: mínimo 2 caracteres.', 'warning');
      return false;
    }
    if (this.usuarioEditando.apellidos.length > 50) {
      Swal.fire('Validación', 'Apellidos: máximo 50 caracteres.', 'warning');
      return false;
    }
    if (!this.campoSoloLetrasValido(this.usuarioEditando.apellidos)) {
      Swal.fire('Validación', 'Apellidos: solo se permiten letras y espacios.', 'error');
      return false;
    }

    this.generarUsuarioEditar();

    if (!this.campoUsuarioValido(this.usuarioEditando.usuario)) {
      Swal.fire('Validación', 'Usuario inválido. Solo letras minúsculas, números, punto, guion y guion bajo.', 'error');
      return false;
    }

    if (this.usuarioEditando.password && this.usuarioEditando.password.length < 6) {
      Swal.fire('Validación', 'La contraseña debe tener mínimo 6 caracteres.', 'warning');
      return false;
    }
    if (this.usuarioEditando.password && this.usuarioEditando.password.length > 50) {
      Swal.fire('Validación', 'La contraseña no debe superar 50 caracteres.', 'warning');
      return false;
    }

    if (!this.usuarioEditando.rol) {
      Swal.fire('Campos incompletos', 'Seleccione un rol para el usuario.', 'warning');
      return false;
    }

    return true;
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
        this.cargarDatosIniciales();
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
        this.cargarDatosIniciales();
      },
      error: (err: any) => Swal.fire('Error', err.error?.mensaje || 'Error al actualizar usuario', 'error')
    });
  }

  cambiarEstado(u: any): void {
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
            this.cargarDatosIniciales();
          },
          error: (err: any) => Swal.fire('Error', err.error?.mensaje || 'Error al cambiar estado', 'error')
        });
      }
    });
  }

  eliminar(id: number): void {
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
            this.cargarDatosIniciales();
          },
          error: (err: any) => Swal.fire('Error', err.error?.mensaje || 'Error al eliminar', 'error')
        });
      }
    });
  }
}