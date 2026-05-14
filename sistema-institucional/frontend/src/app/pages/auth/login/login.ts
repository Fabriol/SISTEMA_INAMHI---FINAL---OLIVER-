import { Component } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { AuthService } from '../../../core/services/auth.service';

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

  constructor(
    private auth: AuthService,
    private router: Router
  ) { }

  ingresar(): void {
    this.error = '';

    if (!this.usuario || !this.password) {
      this.error = 'Ingrese usuario y contraseña';
      return;
    }

    this.cargando = true;

    this.auth.login({
      usuario: this.usuario,
      password: this.password
    }).subscribe({
      next: (res: any) => {

        // guardar sesión
        localStorage.setItem('token', res.token);
        localStorage.setItem('usuario', JSON.stringify(res.usuario));

        // redirigir
        this.router.navigate(['/dashboard']);

        this.cargando = false;
      },
      error: (err: any) => {
        this.error = err.error?.mensaje || 'Error al iniciar sesión';
        this.cargando = false;
      }
    });
  }
}