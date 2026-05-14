import { Injectable } from '@angular/core';
import { ApiService } from './api.service';

@Injectable({ providedIn: 'root' })
export class DocumentosService {
    constructor(private api: ApiService) { }

    listar() {
        return this.api.get('documentos');
    }

    crear(data: any) {
        return this.api.post('documentos', data);
    }

    eliminar(id: number) {
        return this.api.delete(`documentos/${id}`);
    }

    actualizar(id: number, data: any) {
        return this.api.put(`documentos/${id}`, data);
    }

    
}