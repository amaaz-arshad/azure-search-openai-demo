import { Helmet } from "react-helmet-async";

import styles from "./AdminLayout.module.css";

/*
 * The Embed demo tab. embed_demo.html stays a backend-served page (/embed-demo); we iframe it
 * here rather than reimplementing its widget-injection + whitelist editor. It is same-origin and
 * shares the internal_tools_admin_session cookie, so its own checkSession() passes and it reveals
 * the admin content directly — no second login. Its internal "Lock page" button logs out the
 * shared session (same cookie), which is acceptable.
 */
export function EmbedDemoTab() {
    return (
        <section className={styles.embedShell}>
            <Helmet>
                <title>Admin · Embed demo</title>
            </Helmet>
            <iframe src="/embed-demo" title="Embed demo" className={styles.embedFrame} />
        </section>
    );
}

export default EmbedDemoTab;
