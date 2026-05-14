import { Routes } from '@angular/router';
import { Login } from './pages/auth/login/login';
import { Dashboard } from './pages/dashboard/dashboard';
import { AuthGuard } from './core/guards/auth.guard';
import { RoleGuard } from './core/guards/role.guard';

export const routes: Routes = [
  {
    path: 'login',
    component: Login
  },

  {
    path: 'dashboard',
    component: Dashboard,
    canActivate: [AuthGuard]
  },

  {
    path: 'usuarios',
    loadComponent: () =>
      import('./pages/usuarios/usuarios').then(m => m.Usuarios),
    canActivate: [AuthGuard, RoleGuard],
    data: {
      roles: ['Administrador']
    }
  },

  {
    path: 'auditoria',
    loadComponent: () =>
      import('./pages/auditoria/auditoria').then(m => m.Auditoria),
    canActivate: [AuthGuard, RoleGuard],
    data: {
      roles: ['Administrador']
    }
  },

  {
    path: 'documentos',
    loadComponent: () =>
      import('./pages/documentos/documentos').then(m => m.Documentos),
    canActivate: [AuthGuard]
  },

  {
    path: 'reportes',
    loadComponent: () =>
      import('./pages/reportes/reportes').then(m => m.Reportes)
  },

  {
    path: '',
    redirectTo: 'login',
    pathMatch: 'full'
  },

  {
    path: '**',
    redirectTo: 'dashboard'
  }
];