/**
 * ModelManager handles the lifecycle and communication with the AI Web Worker.
 */
class ModelManager {
    constructor() {
        this.worker = null;
        this.isReady = false;
        this.initPromise = null;
        this.pendingRequests = new Map();
    }

    /**
     * Initialize the AI worker. Can be called multiple times, returns same promise.
     */
    async init() {
        if (this.initPromise) return this.initPromise;

        this.initPromise = new Promise((resolve, reject) => {
            try {
                // In Vite, you can use new Worker(new URL('./ai-worker.js', import.meta.url))
                // or just reference the public path if it's there.
                this.worker = new Worker('/ai-worker.js', { type: 'module' });

                this.worker.onmessage = (e) => {
                    const { type, payload, error } = e.data;

                    if (type === 'READY') {
                        this.isReady = true;
                        console.log('[ModelManager] AI Worker Ready');
                        resolve();
                    } else if (type === 'RESULTS') {
                        const { originalFileId, faces } = payload;
                        const resolver = this.pendingRequests.get(originalFileId);
                        if (resolver) {
                            resolver.resolve(faces);
                            this.pendingRequests.delete(originalFileId);
                        }
                    } else if (type === 'ERROR') {
                        console.error('[ModelManager] Worker Error:', error);
                        // If it's a global error, we might need to reject the init
                        if (!this.isReady) reject(new Error(error));
                    }
                };

                this.worker.onerror = (err) => {
                    console.error('[ModelManager] Worker Script Error:', err);
                    reject(err);
                };

                this.worker.postMessage({ type: 'INIT' });
            } catch (err) {
                reject(err);
            }
        });

        return this.initPromise;
    }

    /**
     * Process a single image file or imageBitmap.
     * @param {File|ImageBitmap} source 
     * @param {string} id Unique ID for this request
     */
    async processImage(source, id) {
        await this.init();

        let imageBitmap;
        if (source instanceof File || source instanceof Blob) {
            imageBitmap = await createImageBitmap(source);
        } else {
            imageBitmap = source;
        }

        return new Promise((resolve, reject) => {
            this.pendingRequests.set(id, { resolve, reject });
            this.worker.postMessage({
                type: 'PROCESS_IMAGE',
                payload: {
                    imageBitmap,
                    originalFileId: id
                }
            }, [imageBitmap]); // Transferable
        });
    }

    /**
     * Process multiple files sequentially or in parallel.
     */
    async processBatch(files, onProgress) {
        const results = [];
        let processed = 0;

        for (const file of files) {
            const id = `${file.name}-${Date.now()}-${Math.random()}`;
            try {
                const faces = await this.processImage(file, id);
                results.push({ file, faces });
            } catch (err) {
                console.error(`Failed to process ${file.name}:`, err);
                results.push({ file, faces: [], error: err.message });
            }
            processed++;
            if (onProgress) onProgress(processed, files.length);
        }

        return results;
    }
}

const modelManager = new ModelManager();
export default modelManager;
