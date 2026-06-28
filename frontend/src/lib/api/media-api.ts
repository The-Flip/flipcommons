/**
 * Media API client — upload, detach, and set-primary.
 *
 * Upload is hand-rolled on XMLHttpRequest for progress events
 * (openapi-fetch can't expose them). Detach and set-primary go
 * through the typed client.
 */

import type { UploadSchema } from './schema';
import client from './client';
import { getCsrfToken } from './csrf';
import { parseApiError } from './parse-api-error';

export type UploadResult = UploadSchema;

// Keep in sync: backend/apps/media/constants.py
export const MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024; // 20 MB
export const IMAGE_ACCEPT = 'image/*,.heic,.heif,.avif';

// ---------------------------------------------------------------------------
// Upload (XHR for progress)
// ---------------------------------------------------------------------------

export interface UploadOptions {
  category: string;
}

class UploadError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = 'UploadError';
  }
}

export function uploadMedia(
  file: File,
  entityType: string,
  publicId: string,
  opts: UploadOptions,
  onProgress?: (pct: number) => void,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append('file', file);
    form.append('entity_type', entityType);
    form.append('public_id', publicId);
    form.append('category', opts.category);

    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/media/upload/');

    const token = getCsrfToken();
    if (token) xhr.setRequestHeader('X-CSRFToken', token);

    if (onProgress) {
      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      });
    }

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as UploadResult);
      } else {
        let message = `Upload failed (${xhr.status})`;
        try {
          const body = JSON.parse(xhr.responseText);
          const parsed = parseApiError(body).message;
          if (parsed) message = parsed;
        } catch {
          // ignore parse errors
        }
        reject(new UploadError(message, xhr.status));
      }
    });

    xhr.addEventListener('error', () => {
      reject(new UploadError('Network error during upload', 0));
    });

    xhr.send(form);
  });
}

// ---------------------------------------------------------------------------
// Detach + set-primary (typed client)
// ---------------------------------------------------------------------------

type MediaActionEndpoint = '/api/media/detach/' | '/api/media/set-primary/';

async function mediaAction(
  endpoint: MediaActionEndpoint,
  entityType: string,
  publicId: string,
  assetUuid: string,
): Promise<void> {
  const { error, response } = await client.POST(endpoint, {
    body: {
      entity_type: entityType,
      public_id: publicId,
      asset_uuid: assetUuid,
    },
  });
  if (!response.ok) {
    throw new Error(error ? parseApiError(error).message : `Request failed (${response.status})`);
  }
}

export function detachMedia(
  entityType: string,
  publicId: string,
  assetUuid: string,
): Promise<void> {
  return mediaAction('/api/media/detach/', entityType, publicId, assetUuid);
}

export function setPrimary(entityType: string, publicId: string, assetUuid: string): Promise<void> {
  return mediaAction('/api/media/set-primary/', entityType, publicId, assetUuid);
}

export async function setCategory(
  entityType: string,
  publicId: string,
  assetUuid: string,
  category: string,
): Promise<void> {
  const { error, response } = await client.POST('/api/media/set-category/', {
    body: {
      entity_type: entityType,
      public_id: publicId,
      asset_uuid: assetUuid,
      category,
    },
  });
  if (!response.ok) {
    throw new Error(error ? parseApiError(error).message : `Request failed (${response.status})`);
  }
}
