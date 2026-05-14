import { Injectable } from '@angular/core';
import { ApiService } from './api.service';

@Injectable({
  providedIn: 'root'
})
export class AuthService {

  constructor(private api: ApiService) {}

  login(data: any) {
    return this.api.post('auth/login', data);
  }

  getToken(): string | null {
    return localStorage.getItem('token');
  }

  getUsuario(): any {
    return JSON.parse(localStorage.getItem('usuario') || '{}');
  }

  logout(): void {
    localStorage.clear();
    window.location.href = '/login';
  }

  isLogged(): boolean {
    return !!this.getToken();
  }
}