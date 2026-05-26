<script lang="ts">
  import { SITE_NAME, pageTitle } from '$lib/constants';
  import LastUpdated from '$lib/components/LastUpdated.svelte';
  import { STATIC_LASTMOD, formatLastUpdated } from '$lib/static-lastmod';
</script>

<svelte:head>
  <title>{pageTitle('Privacy Policy')}</title>
</svelte:head>

<h1>Privacy Policy</h1>
<LastUpdated>Last updated: {formatLastUpdated(STATIC_LASTMOD['/(legal)/privacy'])}</LastUpdated>

<h2>How We Operate</h2>
<p>
  {SITE_NAME} is a public knowledge project, not an advertising or growth-optimization platform. We do
  not design for engagement addiction, infinite-scroll optimization, or manipulative notification funnels.
</p>

<h2>Information We Collect</h2>
<p>
  {SITE_NAME} collects only the minimal information needed to operate and improve the service:
</p>
<ul>
  <li>
    <strong>Account information</strong> — if you create an account: your email address, your chosen username,
    and your first and last name (provided by your sign-in provider).
  </li>
  <li>
    <strong>Usage data</strong> — standard web server logs including IP addresses, browser type, and pages
    visited.
  </li>
  <li>
    <strong>Uploaded images</strong> — files you upload. All metadata (including GPS, camera info, and
    timestamps) is stripped before storage.
  </li>
</ul>

<h2>Information We Publish</h2>
<p>
  Only your username is shown publicly — for example, on contributions you make and on your profile
  page. Your email address and real name are never displayed to other users.
</p>

<h2>How We Don't Use Information</h2>
<p>We do not sell personal information to third parties. We do not:</p>
<ul>
  <li>share analytics with ad networks or participate in behavioral advertising</li>
  <li>perform cross-site tracking</li>
  <li>fingerprint visitors, build shadow profiles, or perform behavioral profiling</li>
</ul>

<h2>Cookies</h2>
<p>
  {SITE_NAME} uses a small number of cookies for essential functionality:
</p>
<ul>
  <li><strong>Session cookie</strong> — maintains your login state.</li>
  <li><strong>CSRF token</strong> — protects against cross-site request forgery.</li>
</ul>
<p>We do not use tracking or advertising cookies.</p>

<h2>Data Retention</h2>
<p>
  Account information is retained while your account is active. Server logs are retained for a
  limited period for operational purposes. To delete your account and associated data, email
  <a href="mailto:privacy@flipcommons.org">privacy@flipcommons.org</a>.
</p>

<h2>Third-Party Services</h2>
<p>
  {SITE_NAME} relies on a number of third-party services to operate:
</p>
<ul>
  <li>
    <strong><a href="https://workos.com">WorkOS</a></strong> — handles sign-in and authentication.
  </li>
  <li>
    <strong><a href="https://railway.com">Railway</a></strong> — hosts the application.
  </li>
  <li>
    <strong><a href="https://bunny.net">Bunny CDN</a></strong> — serves images and other media.
  </li>
  <li>
    <strong><a href="https://www.idrive.com/e2/">iDrive e2</a></strong> — stores uploaded files.
  </li>
  <li>
    <strong><a href="https://sentry.io">Sentry</a></strong> — receives error reports when something breaks
    in your browser or on our servers, so we can fix it. Reports include your account ID and username
    if you're signed in; personally identifying information like IP addresses, email addresses, request
    bodies, and query strings are stripped before delivery. Does not use cookie tracking or record browser
    sessions.
  </li>
  <li>
    <strong><a href="https://posthog.com">PostHog</a></strong> — helps us understand which parts of
    the site are used and where contributors get stuck, so we can improve them. We notify PostHog
    each time you do specific actions like visit a page, successfully save an edit, or have an
    upload fail. Each notification includes the page you were on (without anything after the
    <code>?</code>
    in the address bar), the site that referred you (if any), and your browser and operating system family.
    We have configured PostHog not to set cookies, not to remember anything about you between visits,
    not to store your IP address, not to silently record the buttons you click or text you type, not to
    record a video of your session, not to run pop-up surveys, not to record your screen or window size,
    and not to capture marketing or ad-tracking tags from the address bar (things like
    <code>utm_source</code>
    or
    <code>gclid</code>) or the search terms that brought you here from Google or Bing. A temporary
    ID groups activities from the same browser tab together and is forgotten when you close the tab.
  </li>
</ul>

<h2>Your Rights</h2>
<p>
  You have the right to access, correct, or delete your personal information. To exercise these
  rights, email <a href="mailto:privacy@flipcommons.org">privacy@flipcommons.org</a>.
</p>

<h2>Changes to This Policy</h2>
<p>
  We may update this policy from time to time. Changes will be posted on this page with an updated
  date.
</p>

<h2>Contact</h2>
<p>
  If you have questions about this privacy policy, email
  <a href="mailto:privacy@flipcommons.org">privacy@flipcommons.org</a>.
</p>
