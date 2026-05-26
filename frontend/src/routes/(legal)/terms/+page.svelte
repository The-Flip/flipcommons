<script lang="ts">
  import { SITE_NAME, pageTitle } from '$lib/constants';
  import LastUpdated from '$lib/components/LastUpdated.svelte';
  import { STATIC_LASTMOD, formatLastUpdated } from '$lib/static-lastmod';
</script>

<svelte:head>
  <title>{pageTitle('Terms of Service')}</title>
</svelte:head>

<h1>Terms of Service</h1>
<LastUpdated>Last updated: {formatLastUpdated(STATIC_LASTMOD['/(legal)/terms'])}</LastUpdated>

<h2>Acceptance of Terms</h2>
<p>
  By accessing or using {SITE_NAME}, you agree to be bound by these Terms of Service. If you do not
  agree to these terms, please do not use the service.
</p>

<h2>Use of the Service</h2>
<p>
  {SITE_NAME} provides a catalog of pinball machine data for informational purposes. You may browse the
  site and use the public API for personal, educational, or commercial projects, subject to the licensing
  terms of the underlying data.
</p>
<p>You agree not to:</p>
<ul>
  <li>
    Systematically scrape or bulk-download the site in a way that degrades service for others.
  </li>
  <li>Misrepresent {SITE_NAME} as the original source of third-party data.</li>
  <li>Use the service for any unlawful purpose.</li>
</ul>

<h2>User Accounts</h2>
<p>
  Some features require an account. You are responsible for maintaining the security of your account
  credentials. {SITE_NAME} reserves the right to suspend or terminate accounts that violate these terms.
</p>

<h2>Intellectual Property</h2>
<p>
  Content in {SITE_NAME} comes from multiple sources, each with its own license. See the
  <a href="/licensing">Licensing</a> page for details on what you may do with specific types of data.
</p>

<h2>Disclaimer of Warranties</h2>
<p>
  {SITE_NAME} is provided "as is" without warranties of any kind. We aggregate data from community sources
  and do not guarantee the accuracy, completeness, or reliability of any information displayed.
</p>

<h2>Limitation of Liability</h2>
<p>
  To the fullest extent permitted by law, {SITE_NAME} and its contributors shall not be liable for any
  damages arising from your use of the service.
</p>

<h2>Changes to These Terms</h2>
<p>
  We may update these terms from time to time. Continued use of the service after changes are posted
  constitutes acceptance of the revised terms.
</p>

<h2>Contact</h2>
<p>
  If you have questions about these terms, email
  <a href="mailto:howdy@flipcommons.org">howdy@flipcommons.org</a>.
</p>
