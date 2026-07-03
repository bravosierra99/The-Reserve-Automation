/**
 * Unit tests for the Cropper.js lifecycle manager
 * (src/reserve_automation/web/static/js/components/cropper-manager.js).
 *
 * Cropper.js itself is not loaded — a stub class stands in for the global
 * `Cropper` constructor. jsdom's HTMLImageElement never reports
 * naturalHeight > 0, so image-loaded state is faked with defineProperty.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/components/cropper-manager.js';

const manager = window.cropperManager;

/** An <img> that cropper-manager treats as fully loaded. */
function loadedImage() {
    const img = document.createElement('img');
    img.src = 'label.jpg';
    Object.defineProperty(img, 'complete', { value: true });
    Object.defineProperty(img, 'naturalHeight', { value: 480 });
    return img;
}

/** An <img> still waiting on its load event. */
function pendingImage() {
    const img = document.createElement('img');
    img.src = 'label.jpg';
    Object.defineProperty(img, 'complete', { value: false });
    Object.defineProperty(img, 'naturalHeight', { value: 0 });
    return img;
}

class FakeCropper {
    constructor(element, config) {
        this.element = element;
        this.config = config;
        this.destroy = vi.fn();
        this.getData = vi.fn(() => ({ x: 10.6, y: 20.2, width: 100.5, height: 200.4 }));
    }
}

beforeEach(() => {
    vi.stubGlobal('Cropper', FakeCropper);
    vi.stubGlobal('fetch', vi.fn());
});

afterEach(() => {
    vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// initializeCropper
// ---------------------------------------------------------------------------

describe('initializeCropper', () => {
    it('initializes immediately on an already-loaded image with merged config', async () => {
        const img = loadedImage();
        const cropper = await manager.initializeCropper(img, { autoCropArea: 0.5 });

        expect(cropper).toBeInstanceOf(FakeCropper);
        expect(cropper.element).toBe(img);
        // Override wins, defaults survive
        expect(cropper.config.autoCropArea).toBe(0.5);
        expect(cropper.config.viewMode).toBe(1);
        expect(cropper.config.movable).toBe(false);
    });

    it('waits for the load event on a pending image', async () => {
        const img = pendingImage();
        const promise = manager.initializeCropper(img);

        expect(img.onload).toBeTypeOf('function');
        img.onload();

        const cropper = await promise;
        expect(cropper).toBeInstanceOf(FakeCropper);
    });

    it('rejects and calls onError when the image fails to load', async () => {
        const img = pendingImage();
        const onError = vi.fn();
        const promise = manager.initializeCropper(img, {}, onError);
        promise.catch(() => {});

        img.onerror();

        await expect(promise).rejects.toThrow('Failed to load image');
        expect(onError).toHaveBeenCalledWith(expect.any(Error));
    });

    it('rejects and calls onError when the Cropper constructor throws', async () => {
        vi.stubGlobal('Cropper', class { constructor() { throw new Error('bad element'); } });
        const onError = vi.fn();

        await expect(manager.initializeCropper(loadedImage(), {}, onError))
            .rejects.toThrow('bad element');
        expect(onError).toHaveBeenCalled();
    });

    it('throws without an image element', async () => {
        await expect(manager.initializeCropper(null)).rejects.toThrow('Image element is required');
    });

    it('throws when the Cropper.js library is not loaded', async () => {
        vi.unstubAllGlobals(); // removes the Cropper stub
        vi.stubGlobal('fetch', vi.fn());
        await expect(manager.initializeCropper(loadedImage()))
            .rejects.toThrow('Cropper.js library not loaded');
    });
});

// ---------------------------------------------------------------------------
// getCropData / destroyCropper
// ---------------------------------------------------------------------------

describe('getCropData', () => {
    it('returns rounded pixel coordinates', () => {
        const cropper = new FakeCropper();
        expect(manager.getCropData(cropper)).toEqual({ x: 11, y: 20, width: 101, height: 200 });
        expect(cropper.getData).toHaveBeenCalledWith(true);
    });

    it('throws without an instance', () => {
        expect(() => manager.getCropData(null)).toThrow('Cropper instance is required');
    });
});

describe('destroyCropper', () => {
    it('destroys the instance', () => {
        const cropper = new FakeCropper();
        manager.destroyCropper(cropper);
        expect(cropper.destroy).toHaveBeenCalled();
    });

    it('swallows destroy errors (already-destroyed instances)', () => {
        const cropper = { destroy: vi.fn(() => { throw new Error('already gone'); }) };
        expect(() => manager.destroyCropper(cropper)).not.toThrow();
    });

    it('ignores null', () => {
        expect(() => manager.destroyCropper(null)).not.toThrow();
    });
});

// ---------------------------------------------------------------------------
// sendCropRequest
// ---------------------------------------------------------------------------

describe('sendCropRequest', () => {
    it('POSTs the crop payload as JSON', async () => {
        global.fetch = vi.fn(async () => ({ ok: true }));

        await manager.sendCropRequest('/api/v1/crop', { x: 1, y: 2, width: 3, height: 4 });

        expect(global.fetch).toHaveBeenCalledWith('/api/v1/crop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ x: 1, y: 2, width: 3, height: 4 }),
        });
    });

    it('throws with status and body text on failure', async () => {
        global.fetch = vi.fn(async () => ({
            ok: false,
            status: 422,
            text: async () => 'bad coords',
        }));

        await expect(manager.sendCropRequest('/api/v1/crop', {}))
            .rejects.toThrow('Crop request failed: 422 bad coords');
    });
});

// ---------------------------------------------------------------------------
// completeCrop — the full workflow
// ---------------------------------------------------------------------------

describe('completeCrop', () => {
    function okJsonResponse(data) {
        return {
            ok: true,
            headers: { get: () => 'application/json' },
            json: async () => data,
        };
    }

    it('sends coordinates merged with additional data, destroys, and calls onSuccess', async () => {
        const cropper = new FakeCropper();
        const onSuccess = vi.fn();
        global.fetch = vi.fn(async () => okJsonResponse({ status: 'cropped' }));

        const result = await manager.completeCrop(
            cropper, '/api/v1/crop', { bottle_id: 'b42' }, onSuccess
        );

        const sent = JSON.parse(global.fetch.mock.calls[0][1].body);
        expect(sent).toEqual({ bottle_id: 'b42', x: 11, y: 20, width: 101, height: 200 });
        expect(cropper.destroy).toHaveBeenCalled();
        expect(onSuccess).toHaveBeenCalledWith({ status: 'cropped' });
        expect(result).toEqual({ status: 'cropped' });
    });

    it('returns null result for non-JSON responses', async () => {
        const cropper = new FakeCropper();
        global.fetch = vi.fn(async () => ({
            ok: true,
            headers: { get: () => 'text/plain' },
        }));

        const result = await manager.completeCrop(cropper, '/api/v1/crop');
        expect(result).toBeNull();
    });

    it('destroys the cropper, calls onError, and rethrows on failure', async () => {
        const cropper = new FakeCropper();
        const onError = vi.fn();
        global.fetch = vi.fn(async () => ({
            ok: false,
            status: 500,
            text: async () => 'server error',
        }));

        await expect(manager.completeCrop(cropper, '/api/v1/crop', {}, null, onError))
            .rejects.toThrow('Crop request failed');
        expect(cropper.destroy).toHaveBeenCalled();
        expect(onError).toHaveBeenCalledWith(expect.any(Error));
    });
});
