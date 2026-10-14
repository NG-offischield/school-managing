import { PORTAL_ROLES } from "@/lib/roles";
import { relayFile } from "@/lib/stream";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(request: Request, { params }: RouteContext<"/ressources/[id]/document">) {
  const { id } = await params;
  const search = new URL(request.url).searchParams;
  const role = search.get("role") ?? "";
  const student = search.get("student") ?? "";
  if (!UUID.test(id) || !(PORTAL_ROLES as string[]).includes(role) || (student && !UUID.test(student))) {
    return new Response("Introuvable.", { status: 404 });
  }
  return relayFile(request, `portal/resources/${id}/document/`, { role, ...(student ? { student } : {}) });
}
