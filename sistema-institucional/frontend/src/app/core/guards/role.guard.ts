import { Injectable, PLATFORM_ID, inject } from '@angular/core';
import { CanActivate, ActivatedRouteSnapshot, Router } from '@angular/router';
import { isPlatformBrowser } from '@angular/common';
import Swal from 'sweetalert2';

@Injectable({
  providedIn: 'root'
})
export class RoleGuard implements CanActivate {

  private platformId = inject(PLATFORM_ID);

  constructor(private router: Router) {}

  canActivate(route: ActivatedRouteSnapshot): boolean {
    if (!isPlatformBrowser(this.platformId)) {
      return false;
    }

    const usuarioStorage = localStorage.getItem('usuario');

    if (!usuarioStorage) {
      this.router.navigate(['/login']);
      return false;
    }

    const usuario = JSON.parse(usuarioStorage);
    const rolesPermitidos = route.data['roles'] as string[];

    if (!rolesPermitidos.includes(usuario.rol)) {
      Swal.fire({
        icon: 'warning',
        title: 'Acceso restringido',
        text: 'Solo el Administrador puede ingresar a esta sección.',
        timer: 1800,
        showConfirmButton: false
      });

      this.router.navigate(['/dashboard']);
      return false;
    }

    return true;
  }
}