import { Routes } from '@angular/router';
import { Login } from './pages/auth/login/login';
import { Dashboard } from './pages/dashboard/dashboard';
import { AuthGuard } from './core/guards/auth.guard';
import { RoleGuard } from './core/guards/role.guard';

export const routes: Routes = [

  // 🔐 LOGIN
  {
    path: 'login',
    component: Login
  },

  // 🏠 DASHBOARD (TODOS AUTENTICADOS)
  {
    path: 'dashboard',
    component: Dashboard,
    canActivate: [AuthGuard]
  },

  // 👤 USUARIOS (SOLO ADMIN)
  {
    path: 'usuarios',
    loadComponent: () =>
      import('./pages/usuarios/usuarios').then(m => m.Usuarios),
    canActivate: [AuthGuard, RoleGuard],
    data: {
      roles: ['Administrador']
    }
  },

  // 📊 AUDITORÍA (SOLO ADMIN)
  {
    path: 'auditoria',
    loadComponent: () =>
      import('./pages/auditoria/auditoria').then(m => m.Auditoria),
    canActivate: [AuthGuard, RoleGuard],
    data: {
      roles: ['Administrador']
    }
  },

  // 📈 REPORTES (SOLO ADMIN)
  {
    path: 'reportes',
    loadComponent: () =>
      import('./pages/reportes/reportes').then(m => m.Reportes),
    canActivate: [AuthGuard, RoleGuard],
    data: {
      roles: ['Administrador']
    }
  },

  // 📄 DOCUMENTOS (TODOS LOS USUARIOS)
  {
    path: 'documentos',
    loadComponent: () =>
      import('./pages/documentos/documentos').then(m => m.Documentos),
    canActivate: [AuthGuard]
  },

  // 🧩 FORMULARIOS DINÁMICOS (TODOS AUTENTICADOS)
  {
    path: 'formularios',
    loadComponent: () =>
      import('./pages/formularios/formularios').then(m => m.Formularios),
    canActivate: [AuthGuard]
  },

  // 🔁 REDIRECCIÓN INICIAL
  {
    path: '',
    redirectTo: 'login',
    pathMatch: 'full'
  },

  // 🚫 RUTA NO ENCONTRADA
  {
    path: '**',
    redirectTo: 'dashboard'
  }
];