import { Provenance } from "@/lib/api";

// §43 source transparency: every factual record shows where it came from and when it
// was last verified, right next to the data itself.
export function ProvenanceLine({ provenance }: { provenance: Provenance }) {
  const isDemo = provenance.verification_status === "unverified_demo";
  return (
    <p className="text-xs text-muted mt-1">
      Source: {provenance.source}
      {provenance.academic_year && ` · ${provenance.academic_year}`}
      {" · "}
      {isDemo ? (
        <span className="font-medium">not yet verified (demo data)</span>
      ) : provenance.last_verified ? (
        `Last verified: ${new Date(provenance.last_verified).toLocaleDateString()}`
      ) : (
        "Verification date unknown"
      )}
    </p>
  );
}
