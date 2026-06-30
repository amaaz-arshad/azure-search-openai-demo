import { IDBPDatabase, openDB } from "idb";
import { IHistoryProvider, Answers, HistoryProviderOptions, HistoryMetaData, HistorySessionMetadata } from "./IProvider";

// Browser chat-history store for dynamic bots. Mirrors the built-in bots' IndexedDB provider: one
// object store keyed by session id, indexed by timestamp for newest-first paged reads.
export class IndexedDBProvider implements IHistoryProvider {
    getProviderName = () => HistoryProviderOptions.IndexedDB;

    private dbName: string;
    private storeName: string;
    private dbPromise: Promise<IDBPDatabase> | null = null;
    private cursorKey: IDBValidKey | undefined;
    private isCursorEnd: boolean = false;

    constructor(dbName: string, storeName: string) {
        this.dbName = dbName;
        this.storeName = storeName;
        this.cursorKey = undefined;
        this.isCursorEnd = false;
    }

    private async init() {
        const storeName = this.storeName;
        if (!this.dbPromise) {
            this.dbPromise = openDB(this.dbName, 1, {
                upgrade(db) {
                    if (!db.objectStoreNames.contains(storeName)) {
                        const store = db.createObjectStore(storeName, { keyPath: "id" });
                        store.createIndex("timestamp", "timestamp");
                    }
                }
            });
        }
        return this.dbPromise;
    }

    resetContinuationToken() {
        this.cursorKey = undefined;
        this.isCursorEnd = false;
    }

    async getNextItems(count: number): Promise<HistoryMetaData[]> {
        const db = await this.init();
        const tx = db.transaction(this.storeName, "readonly");
        const store = tx.objectStore(this.storeName);
        const index = store.index("timestamp");

        if (this.isCursorEnd) {
            return [];
        }

        let cursor = this.cursorKey ? await index.openCursor(IDBKeyRange.upperBound(this.cursorKey), "prev") : await index.openCursor(null, "prev");

        if (!cursor) {
            this.isCursorEnd = true;
            return [];
        }

        const loadedItems: HistoryMetaData[] = [];
        for (let i = 0; i < count && cursor; i++) {
            loadedItems.push(cursor.value);
            cursor = await cursor.continue();
        }

        if (!cursor) {
            this.isCursorEnd = true;
        }

        this.cursorKey = cursor?.key;

        return loadedItems;
    }

    async addItem(id: string, answers: Answers, metadata?: HistorySessionMetadata): Promise<void> {
        const timestamp = new Date().getTime();
        const db = await this.init();
        const tx = db.transaction(this.storeName, "readwrite");
        const current = await tx.objectStore(this.storeName).get(id);
        if (current) {
            await tx.objectStore(this.storeName).put({ ...current, id, timestamp, answers, metadata });
        } else {
            const firstQuestion = answers[0]?.[0] ?? "";
            const title = firstQuestion.length > 50 ? firstQuestion.substring(0, 50) + "..." : firstQuestion;
            await tx.objectStore(this.storeName).add({ id, title, timestamp, answers, metadata });
        }
        await tx.done;
    }

    async getItem(id: string): Promise<Answers | null> {
        const db = await this.init();
        const tx = db.transaction(this.storeName, "readonly");
        const item = await tx.objectStore(this.storeName).get(id);
        if (!item) {
            return null;
        }
        return item.answers as Answers;
    }

    async deleteItem(id: string): Promise<void> {
        const db = await this.init();
        await db.delete(this.storeName, id);
    }
}
