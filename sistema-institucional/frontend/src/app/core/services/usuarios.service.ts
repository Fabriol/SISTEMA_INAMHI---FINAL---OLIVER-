import { Injectable } from '@angular/core';
import { ApiService } from './api.service';

@Injectable({ providedIn: 'root' })
export class UsuariosService {
  constructor(private api: ApiService) { }

  listar() {
    return this.api.get('usuarios');
  }

  crear(data: any) {
    return this.api.post('usuarios', data);
  }

  actualizar(id: number, data: any) {
    return this.api.put(`usuarios/${id}`, data);
  }

  eliminar(id: number) {
    return this.api.delete(`usuarios/${id}`);
  }

  roles() {
    return this.api.get('roles');
  }

  cambiarEstado(id: number, estado: string) {
    return this.api.put(`usuarios/${id}/estado`, { estado });
  }
}