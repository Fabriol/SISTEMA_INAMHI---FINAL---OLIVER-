import { Injectable, PLATFORM_ID, inject } from '@angular/core';
import { CanActivate, Router } from '@angular/router';
import { isPlatformBrowser } from '@angular/common';
import Swal from 'sweetalert2';

@Injectable({
  providedIn: 'root'
})
export class AuthGuard implements CanActivate {

  private platformId = inject(PLATFORM_ID);

  constructor(private router: Router) {}

  canActivate(): boolean {
    if (!isPlatformBrowser(this.platformId)) {
      return false;
    }

    const token = localStorage.getItem('token');
    const usuario = localStorage.getItem('usuario');

    if (!token || !usuario || token === 'null' || token === 'undefined') {
      this.limpiarSesion();

      Swal.fire({
        icon: 'warning',
        title: 'Sesión requerida',
        text: 'Debe iniciar sesión para continuar',
        timer: 1500,
        showConfirmButton: false
      });

      this.router.navigate(['/login']);
      return false;
    }

    return true;
  }

  private limpiarSesion(): void {
    localStorage.removeItem('token');
    localStorage.removeItem('usuario');
  }
}