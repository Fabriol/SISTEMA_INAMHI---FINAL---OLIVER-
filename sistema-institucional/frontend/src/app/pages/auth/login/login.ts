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

  constructor(
    private auth: AuthService,
    private router: Router,
    private cdr: ChangeDetectorRef
  ) {}

  validarUsuario(): boolean {
    const regex = /^[a-zA-Z0-9._-]+$/;

    if (!this.usuario.trim()) {
      this.mostrarError('Ingrese su usuario');
      return false;
    }

    if (!regex.test(this.usuario)) {
      this.mostrarError('Usuario inválido');
      return false;
    }

    return true;
  }

  validarPassword(): boolean {
    if (!this.password.trim()) {
      this.mostrarError('Ingrese su contraseña');
      return false;
    }

    if (this.password.length < 4) {
      this.mostrarError('La contraseña debe tener mínimo 4 caracteres');
      return false;
    }

    return true;
  }

  mostrarError(mensaje: string): void {
    this.error = mensaje;
    this.cargando = false;
    this.cdr.detectChanges();

    Swal.fire({
      icon: 'error',
      title: 'Error',
      text: mensaje,
      timer: 1600,
      showConfirmButton: false
    });
  }

  ingresar(): void {
    if (this.cargando) return;

    this.error = '';
    this.usuario = this.usuario.trim().toLowerCase();

    if (!this.validarUsuario()) return;
    if (!this.validarPassword()) return;

    this.cargando = true;
    this.cdr.detectChanges();

    this.auth.login({
      usuario: this.usuario,
      password: this.password
    }).pipe(
      timeout(1500),

      catchError((err: any) => {
        if (err.status === 401) {
          this.mostrarError('Usuario o contraseña incorrectos');
        } else if (err.status === 403) {
          this.mostrarError('Usuario inhabilitado');
        } else if (err.name === 'TimeoutError') {
          this.mostrarError('El servidor tardó demasiado');
        } else {
          this.mostrarError(err.error?.mensaje || 'Error al iniciar sesión');
        }

        return of(null);
      }),

      finalize(() => {
        this.cargando = false;
        this.cdr.detectChanges();
      })
    ).subscribe((res: any) => {
      if (!res) return;

      localStorage.setItem('token', res.token);
      localStorage.setItem('usuario', JSON.stringify(res.usuario));

      this.router.navigate(['/dashboard']);
    });
  }
}