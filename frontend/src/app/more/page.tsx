import Link from "next/link";

import { Icon } from "@/components/icons";
import { PageHeader } from "@/components/ui";
import { brand } from "@/config/brand";

export default function MorePage() {
  return (
    <>
      <PageHeader eyebrow={brand.tagline} title="More" description="The quieter corners of your JournalMe workspace." />
      <section className="more-grid">
        <Link className="card more-card" href="/captures"><Icon name="capture" /><div><h2>Captures</h2><p>Open screenshots and context saved from Companion.</p></div><Icon name="arrow" /></Link>
        <Link className="card more-card" href="/analytics"><Icon name="analytics" /><div><h2>Analytics</h2><p>Study symbols, timing, setups, and mistakes.</p></div><Icon name="arrow" /></Link>
        <Link className="card more-card" href="/playbooks"><Icon name="playbook" /><div><h2>Playbooks</h2><p>Edit trading plans and adherence checklists.</p></div><Icon name="arrow" /></Link>
        <Link className="card more-card" href="/review"><Icon name="review" /><div><h2>Reviews</h2><p>Trade queue plus weekly and monthly reviews.</p></div><Icon name="arrow" /></Link>
        <Link className="card more-card" href="/accounts"><Icon name="accounts" /><div><h2>Accounts</h2><p>Manage accounts, notes, and prop rules.</p></div><Icon name="arrow" /></Link>
        <Link className="card more-card" href="/imports"><Icon name="import" /><div><h2>Imports & quality</h2><p>Review source sessions and reconciliation evidence.</p></div><Icon name="arrow" /></Link>
        <Link className="card more-card" href="/settings"><Icon name="settings" /><div><h2>Settings</h2><p>Preferences, goals, exports, and backups.</p></div><Icon name="arrow" /></Link>
      </section>
    </>
  );
}
