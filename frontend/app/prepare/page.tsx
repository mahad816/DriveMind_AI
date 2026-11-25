import { redirect } from "next/navigation";
/** Preparation lives in the tray now; the library is where documents are chosen. */
export default function Prepare() { redirect("/files"); }
