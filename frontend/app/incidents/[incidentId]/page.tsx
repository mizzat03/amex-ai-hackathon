import { IncidentWorkspace } from "@/components/investigator/incident-workspace";

export default async function Page({ params }: { params: Promise<{ incidentId: string }> }): Promise<React.JSX.Element> {
  const { incidentId } = await params;
  return <IncidentWorkspace incidentId={incidentId} />;
}
