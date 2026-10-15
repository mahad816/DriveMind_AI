import { sessionOwner, sessionRevision } from "@/lib/api/session-events";
import type { DriveFileListResponse } from "@/lib/api/types";

export const INVENTORY_DISPLAY_EVENT = "drivemind:inventory-display";
export type InventoryCounts = { total: number; indexed: number; failed: number; skipped: number };
export const EMPTY_INVENTORY_COUNTS: InventoryCounts = { total: 0, indexed: 0, failed: 0, skipped: 0 };
export type InventoryNotice = { owner: string; revision: number; counts: InventoryCounts | null };
let version = 0;
let nextRead = 0;
export const inventoryDisplayVersion = () => version;
export const beginInventoryRead = () => ++nextRead;
export function inventoryCounts(inventory: DriveFileListResponse, owner: string): InventoryCounts {
  if (!Array.isArray(inventory.files) || inventory.files.some(file => file.user_id !== owner))
    throw new Error("Inventory owner could not be verified");
  return { total: inventory.files.length, indexed: inventory.files.filter(file => file.status === "indexed").length,
    failed: inventory.files.filter(file => file.status === "failed").length, skipped: inventory.files.filter(file => file.status === "skipped").length };
}
/** Display notification only, never a processing cache or authorization proof.
 * No file names/content, persistence, polling or additional requests.
 */
export function publishInventoryRead(read: number, owner: string | null, revision: number, counts: InventoryCounts | null) {
  if (read <= version || !owner || sessionOwner() !== owner || sessionRevision() !== revision || (typeof window === "undefined" || typeof window.dispatchEvent !== "function")) return;
  version = read;
  try { window.dispatchEvent(new CustomEvent<InventoryNotice>(INVENTORY_DISPLAY_EVENT, { detail: { owner, revision, counts } })); } catch { /* Advisory updates never change API outcomes. */ }
}
