import { Component, ChangeDetectorRef } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';
import { catchError, finalize, of, timeout } from 'rxjs';
import Swal from 'sweetalert2';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './login.html',
  styleUrl: './login.scss'
})
export class Login {

  usuario = '';
  password = '';
  error = '';
  cargando = false;
  mostrarPassword = false;

  private alertaActiva = false;

  constructor(
    private auth: AuthService,
    private router: Router,
    private cdr: ChangeDetectorRef
  ) { }

  usuarioValido(valor: string): boolean {
    return /^[a-zA-Z0-9._-]+$/.test(valor || '');
  }

  limpiarUsuario(): void {
    this.usuario = String(this.usuario || '')
      .trim()
      .toLowerCase()
      .replace(/\s+/g, '');
  }

  formularioLoginValido(): boolean {
    const usuarioLimpio = String(this.usuario || '').trim();

    return (
      !!usuarioLimpio &&
      !!this.password &&
      usuarioLimpio.length >= 3 &&
      usuarioLimpio.length <= 30 &&
      this.password.length >= 6 &&
      this.password.length <= 50 &&
      !usuarioLimpio.includes(' ') &&
      this.usuarioValido(usuarioLimpio)
    );
  }

  validarUsuario(): boolean {
    this.limpiarUsuario();

    if (!this.usuario) {
      this.mostrarError('Ingrese su usuario');
      return false;
    }

    if (this.usuario.length < 3) {
      this.mostrarError('El usuario debe tener mínimo 3 caracteres');
      return false;
    }

    if (this.usuario.length > 30) {
      this.mostrarError('El usuario no debe superar 30 caracteres');
      return false;
    }

    if (this.usuario.includes(' ')) {
      this.mostrarError('El usuario no debe contener espacios');
      return false;
    }

    if (!this.usuarioValido(this.usuario)) {
      this.mostrarError('Usuario inválido. Use letras, números, punto, guion o guion bajo');
      return false;
    }

    return true;
  }

  validarPassword(): boolean {
    if (!this.password || !this.password.trim()) {
      this.mostrarError('Ingrese su contraseña');
      return false;
    }

    if (this.password.length < 6) {
      this.mostrarError('La contraseña debe tener mínimo 6 caracteres');
      return false;
    }

    if (this.password.length > 50) {
      this.mostrarError('La contraseña no debe superar 50 caracteres');
      return false;
    }

    return true;
  }

  mostrarError(mensaje: string): void {
    this.error = mensaje;
    this.cargando = false;
    this.cdr.detectChanges();

    if (this.alertaActiva) return;

    this.alertaActiva = true;

    Swal.fire({
      icon: 'error',
      title: 'Acceso denegado',
      text: mensaje,
      confirmButtonText: 'Intentar nuevamente',
      confirmButtonColor: '#dc2626',
      background: '#ffffff',
      color: '#0f172a',
      width: 430,
      timer: 2200,
      timerProgressBar: true
    }).then(() => {
      this.alertaActiva = false;
    });
  }

  limpiarError(): void {
    this.error = '';
  }

  ingresar(): void {
    if (this.cargando) return;

    this.error = '';
    this.limpiarUsuario();

    if (!this.validarUsuario()) return;
    if (!this.validarPassword()) return;

    if (!this.formularioLoginValido()) {
      this.mostrarError('Complete correctamente sus credenciales');
      return;
    }

    this.cargando = true;
    this.cdr.detectChanges();

    this.auth.login({
      usuario: this.usuario,
      password: this.password
    }).pipe(
      timeout(8000),

      catchError((err: any) => {
        if (err.status === 401) {
          this.mostrarError('Usuario o contraseña incorrectos');
        } else if (err.status === 403) {
          this.mostrarError('Usuario inhabilitado. Contacte al administrador');
        } else if (err.status === 0) {
          this.mostrarError('No se pudo conectar con el servidor');
        } else if (err.name === 'TimeoutError') {
          this.mostrarError('El servidor tardó demasiado en responder');
        } else {
          this.mostrarError(
            err.error?.mensaje ||
            err.error?.error ||
            'Error al iniciar sesión'
          );
        }

        return of(null);
      }),

      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((res: any) => {
      if (!res) return;

      if (!res.token || !res.usuario) {
        this.mostrarError('Respuesta inválida del servidor');
        return;
      }

      localStorage.setItem('token', res.token);
      localStorage.setItem('auth_token', res.token);
      localStorage.setItem('usuario', JSON.stringify(res.usuario));
      localStorage.setItem('user_role', res.usuario?.rol || '');

      Swal.fire({
        icon: 'success',
        title: 'Acceso correcto',
        text: `Bienvenido, ${res.usuario?.nombres || this.usuario}`,
        confirmButtonText: 'Continuar',
        confirmButtonColor: '#2563eb',
        background: '#ffffff',
        color: '#0f172a',
        width: 430,
        timer: 1400,
        timerProgressBar: true
      }).then(() => {
        this.router.navigate(['/dashboard']);
      });
    });
  }
}