import { Injectable } from '@angular/core';
import { CanActivate, ActivatedRouteSnapshot, Router } from '@angular/router';

@Injectable({
  providedIn: 'root'
})
export class RoleGuard implements CanActivate {

  constructor(private router: Router) {}

  canActivate(route: ActivatedRouteSnapshot): boolean {
    const usuario = JSON.parse(localStorage.getItem('usuario') || '{}');
    const rolesPermitidos = route.data['roles'] as string[];

    if (!usuario?.rol) {
      this.router.navigate(['/login']);
      return false;
    }

    if (!rolesPermitidos.includes(usuario.rol)) {
      alert('No tienes permisos para acceder a esta sección.');
      this.router.navigate(['/dashboard']);
      return false;
    }

    return true;
  }
}