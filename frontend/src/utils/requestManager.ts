export class RequestManager {
    private static instance: RequestManager;
    private requests = new Map<string, { abort: () => void }>();

    private constructor() { }

    public static getInstance(): RequestManager {
        if (!RequestManager.instance) {
            RequestManager.instance = new RequestManager();
        }
        return RequestManager.instance;
    }

    public register(id: string, abort: () => void) {
        this.requests.set(id, { abort });
    }

    public unregister(id: string) {
        this.requests.delete(id);
    }

    public abort(id: string) {
        const request = this.requests.get(id);
        if (request) {
            request.abort();
            this.unregister(id);
        }
    }

    public abortAll() {
        this.requests.forEach((request) => request.abort());
        this.requests.clear();
    }
}

export const requestManager = RequestManager.getInstance();
