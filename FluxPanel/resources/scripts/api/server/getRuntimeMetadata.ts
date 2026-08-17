import http from '@/api/http';

export interface ServerRuntimeMetadata {
    minecraftVersion: string | null;
    software: string | null;
}

export default (server: string): Promise<ServerRuntimeMetadata> =>
    http.get(`/api/client/servers/${server}/runtime-metadata`).then(({ data: { attributes } }) => ({
        minecraftVersion: attributes.minecraft_version || null,
        software: attributes.software || null,
    }));
