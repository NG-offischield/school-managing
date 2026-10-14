import { relayFile } from "@/lib/stream";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A published, signed release APK of an application whose role the user holds (checked by Django). */
export async function GET(request: Request, { params }: RouteContext<"/applications/[id]/telecharger">) {
  const { id } = await params;
  if (!UUID.test(id)) return new Response("Introuvable.", { status: 404 });
  return relayFile(request, `portal/apps/${id}/download/`);
}
