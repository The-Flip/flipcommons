# Talk Pages

What a Talk Page should be in this project, based on how comparable knowledge and community systems handle page-level discussion.

## Background and Business Rationale

This project is trying to solve a specific problem: durable preservation of pinball knowledge, not just short-term community activity. The project wants authoritative catalog pages and historical essays that can improve over time, survive the loss of any one contributor, and still feel alive rather than frozen. That creates a recurring product need: when two good-faith contributors disagree about a fact, a source, a timeline, or how a page should be framed, where does that disagreement go?

If there is no answer, the disagreement gets expressed in worse ways:

- people silently overwrite each other
- pages oscillate between competing versions
- corrections happen in private channels and are lost
- contributors conclude that editing is social friction and stop participating

This is the business case for Talk Pages. The point is not to add "community" in the abstract. The point is to reduce the operating cost of maintaining trustworthy pages in a volunteer-run system.

That matters especially for this project because of the project's constraints:

- The site carries a museum brand, so quality failures are more expensive than on a hobby forum.
- The contributor base is initially small, knowledgeable, and mission-driven rather than mass-market.
- There is no dedicated moderation staff, so any solution that depends on manual editorial arbitration does not scale.
- The long-term value is in compounding knowledge, not in maximizing comments per session.

Under those conditions, the right question is not "should this project have discussion?" It is "what kind of discussion makes the canonical knowledge base better, and what kind simply creates another place to manage?"

The strongest rationale for Talk Pages is that they can turn conflict and uncertainty into durable editorial memory. A good Talk Page records why a source was preferred, why a claim was scoped narrowly, why a disputed anecdote was excluded, or what evidence would be needed to revisit a decision. That is valuable institutional memory. It lowers future confusion, lowers repeated argument, and makes the site more maintainable without paid staff.

The weak rationale for Talk Pages is generic engagement. General conversation can create activity, but activity is not the same thing as durable knowledge. If this project wants a place for stories, opinions, troubleshooting, buying advice, or social interaction, that is a different product surface with different incentives and moderation needs.

## Prior Art

Comparable systems consistently separate different kinds of discussion instead of treating them as one thing.

### Wikipedia / MediaWiki

[MediaWiki's Help:Talk pages](https://www.mediawiki.org/wiki/Help:Talk_pages) defines talk pages as a discussion space attached to each page. In practice, Wikipedia uses them primarily to improve the article, not to host casual conversation. Wikimedia has invested in [DiscussionTools](https://www.mediawiki.org/wiki/Help:DiscussionTools/en) for replying, subscribing, and navigating threads more easily, which suggests that page-attached discussion remains important when many people co-maintain long-lived pages.

The key lesson is not just that talk pages exist. It is that they have a narrow job: support editorial coordination around the canonical page. They are for questions like:

- is this source reliable enough for this claim?
- should this anecdote be included?
- did we already resolve this timeline dispute?

Wikipedia's system also shows the cost side. Talk pages can become dense, procedural, and intimidating. They are useful when the page itself is collaboratively maintained and when editorial memory matters. They are poor as lightweight social spaces.

#### Issues with Wikipedia Talk Pages

Wikipedia's talk pages are not a structured discussion system in the usual modern sense. A talk page is a wiki page in a discussion namespace paired with a subject page: `Talk:English Springer Spaniel` is the discussion counterpart of `English Springer Spaniel`, just as `Template talk:` and `Category talk:` pages are paired with pages in their respective namespaces. The pairing is a built-in MediaWiki mechanism, but the conversation within the page is primarily wikitext organized by community convention.

A topic is normally a section heading, a comment is a block of text, and a reply is indicated by indentation. Editors sign their contributions by entering `~~~~`, which MediaWiki expands into a username and timestamp when the edit is saved. Those conventions make the document look like a discussion, but the underlying model does not give each contribution a durable comment identity or store an explicit parent-child reply relationship. Editing a discussion is therefore still editing a shared document, even when the interface offers section editing or a reply button.

That architecture has genuine strengths. Talk pages inherit revision history, diffs, rollback, watchlists, links, templates, categories, and flexible collaborative editing from the wiki page model. Editors can reorganize a discussion, repair markup, summarize an outcome, and preserve the entire editorial record without MediaWiki needing a separate discussion subsystem. It is a powerful example of obtaining broad functionality from a small set of composable primitives.

The same architecture also imposes substantial usability and information-architecture costs:

- Reply structure is encoded in editable text rather than represented as data, so deep or inconsistent indentation can make a conversation difficult to follow.
- Authorship and timestamps are inserted into the page text rather than intrinsically attached to comment objects, which makes unsigned, malformed, moved, or edited contributions possible.
- Multiple topics accumulate in one mutable document. Active pages grow large and eventually depend on manual or bot-assisted archiving, splitting the editorial record across an archive scheme that readers must learn to navigate.
- A section heading is not a durable topic object. Renaming, moving, merging, or archiving sections can make references and discovery less reliable than they would be in a system with stable topic identities.
- The page has no intrinsic lifecycle for a question or dispute. Whether a discussion is open, resolved, superseded, or merely abandoned must be inferred from prose, templates, or local convention.
- Editing shared wikitext exposes participants to formatting mistakes and edit conflicts that a comment-oriented interface can avoid.
- Notifications and subscriptions are harder to define because the storage model describes page revisions, not semantically distinct topics and replies.

[DiscussionTools](https://www.mediawiki.org/wiki/Help:DiscussionTools/en) improves the experience with affordances such as reply controls, new-topic forms, topic subscriptions, and enhanced navigation. Importantly, it generally works with the existing wikitext talk-page conventions rather than replacing them with a native thread-and-comment data model. This preserves compatibility with established pages, workflows, templates, and bots, but it also means the interface must interpret document structure as discussion structure.

Wikimedia did try to replace this model. It developed [Structured Discussions, originally called Flow](https://www.mediawiki.org/wiki/Structured_Discussions), in which topics and posts were discrete objects with automatic signatures, per-topic subscriptions, stable permalinks, explicit moderation actions, and no need for manual indentation or archiving. On the dimensions where wikitext talk pages most obviously resemble a broken forum, Flow was the more coherent design. Yet it did not replace wikitext talk pages across Wikipedia.

The important reason was social compatibility, expressed through technical workflows. Experienced editors were not merely using talk pages to append comments. Over many years they had learned to treat the entire discussion page as shared, malleable working material: they moved and reorganized conversations, split and merged sections, transcluded discussions, inserted templates and tables, annotated or collapsed debates, built bot-driven archival processes, and inspected whole-page histories and diffs. Local communities had accumulated policies and coordination practices around that freedom. Flow made the basic act of replying easier, especially for newcomers, but its structured objects constrained the page-level manipulation on which experienced editors and community workflows depended. It also represented history at the thread level rather than preserving the familiar whole-page revision model. A replacement therefore had to reproduce a very large set of evolved use cases before the communities doing the most editorial coordination would regard it as an adequate substitute.

This was not simply irrational resistance to a better interface. The open wikitext document was both the source of talk pages' usability problems and a general-purpose coordination substrate. Structure removed accidental complexity, but it also removed affordances that the community had turned into capabilities. In its [2019 Talk Pages Consultation](https://www.mediawiki.org/wiki/Talk_pages_consultation_2019/Phase_1_report/en), the Wikimedia Foundation concluded that experienced contributors favored the flexibility and continuity of wikitext, that important workflows depended on manipulating it, and that replacement systems such as Flow would have to handle an intimidating range of existing use cases to achieve adoption. The resulting product direction was to improve wikitext talk pages rather than replace them: layer automatic replying, indentation, signatures, and subscriptions onto the established substrate.

The lesson for Flipcommons is stronger than "users dislike change." A collaboration system becomes partly defined by the practices its users invent around it. Replacing its data model later can invalidate capabilities that were never written into the original requirements because they emerged through use. Flipcommons has the advantage of choosing a structured model before such dependencies exist, but it should not make that model rigid. It should deliberately preserve escape hatches for summarizing outcomes, reorganizing related topics, linking and quoting across discussions, attaching supporting material, and viewing discussion history at useful scopes. Otherwise it risks solving the visible mechanics of comments while preventing the unanticipated editorial practices that make a knowledge community effective.

Flipcommons does not yet carry Wikipedia's compatibility burden. It can treat page-attached discussion as a first-class relationship while storing topics, comments, replies, authorship, timestamps, subscriptions, and resolution state explicitly. The goal should not be to discard what Wikipedia's model does well: discussions should still be durable, linkable, searchable, historically inspectable, adaptable by their participants, and closely connected to changes in the canonical page. The opportunity is to preserve those properties without making contributors simulate a discussion system by collaboratively editing one giant text document.

### Fandom

Fandom's product split is instructive because it explicitly broke "discussion" into multiple surfaces:

- [Talk pages](https://community.fandom.com/wiki/Help:Talk_pages) for page-level discussion
- [Comments](https://community.fandom.com/wiki/Help:Comments) for lightweight reactions on an article
- [Discussions](https://community.fandom.com/wiki/Help:Discussions) for broader social/community conversation

That split reflects a real product truth: users want different things from these surfaces, and combining them usually degrades all of them. When page-improvement discussion, reader reaction, and community chat all live in one place, the highest-noise use case tends to dominate.

For this project, Fandom is useful mostly as a caution. If this project ships Talk Pages, they should not be asked to double as comments and not be asked to double as forums.

### MusicBrainz

[MusicBrainz](https://musicbrainz.org/doc/Introduction_to_Editing) is one of the closest structural analogs to this project: a mission-driven, community-maintained knowledge base with a serious data quality culture. But it does not center article-like talk pages. Instead, communication is tied closely to edits themselves via [edit notes](https://musicbrainz.org/doc/Edit_Note), voting, and review.

The lesson is that some knowledge systems do not need a broad page-level discussion layer if their dominant coordination problem is review of specific changes. MusicBrainz's approach is better when the main question is "should this edit land?" rather than "how should this page represent an unresolved topic over time?"

For this project, this suggests Talk Pages are most justified around long-lived pages with interpretive or historiographic questions. They are less essential if the issue is a narrow, transactional correction that could be handled by edit notes, flags, or structured review.

### Discogs

Discogs also splits communication by job. Its database contribution workflow emphasizes [submission notes](https://support.discogs.com/hc/en-us/articles/360004016634-What-Do-I-Write-In-The-Submission-Notes-Field-) and database guidelines for structured corrections, while broader community conversation happens elsewhere. Release pages also support [reviews](https://support.discogs.com/hc/en-us/articles/17114733929229-Release-Page-Guide), which are explicitly opinion surfaces rather than editorial workspaces.

This matters because it demonstrates another recurring pattern: systems that care about authoritative catalog data tend to keep the "why I changed this" conversation close to the change, and keep opinion/reaction in a separate lane.

For this project, Discogs reinforces that Talk Pages should not become review surfaces, opinion surfaces, or all-purpose comments. If they exist, their value is in deliberation over the canonical page.

### BoardGameGeek

[BoardGameGeek game entries](https://boardgamegeek.com/wiki/page/game_entry) include forums directly associated with a game page. This creates active game-specific conversation and gives users a clear place to ask questions, discuss strategy, debate editions, and share opinions.

That model works for community engagement, but it has a different outcome profile. Forums are excellent at producing activity and accumulated discussion. They are much worse at producing concise institutional memory unless someone regularly curates thread outcomes back into the page itself.

BoardGameGeek shows what happens when page-attached discussion is optimized for community utility rather than editorial maintenance. It can be vibrant, but it does not automatically improve the canonical description. This project should only copy this model if it wants a forum product. It should not copy it under the label of Talk Pages.

### OpenStreetMap

[OpenStreetMap Notes](https://wiki.openstreetmap.org/wiki/Notes) show the opposite extreme: a page- or map-attached comment surface that is tightly scoped to reporting and resolving a specific problem. The documentation explicitly frames Notes as issue-reporting rather than general discussion.

This is useful because it shows another option for this project. Some disputes or corrections are not "talk page" problems at all. They are issue-reporting problems. If the goal is simply "this photo is misdated" or "this attribution is wrong," a narrow flag or correction workflow may be much better than a reusable discussion page.

### iNaturalist

iNaturalist combines open contribution with mission-driven stewardship, which makes it strategically relevant even though its object model is different. Much of the discussion on the site is attached to specific observations, taxa, or curation actions, and the platform also uses flags and curator processes for issues that need attention.

The lesson here is motivational rather than structural. Contributors will tolerate more editorial process when they believe they are serving a mission larger than the platform. This project likely has that same advantage because preserving pinball history is intrinsically meaningful to many contributors. That makes a focused, evidence-oriented discussion surface more plausible than it would be on a generic UGC site.

## Theory for How to Evaluate Features

The research suggests that this project should not ask "what discussion features are common?" It should ask "what jobs must a Talk Page do in order to improve the knowledge base?"

That leads to a simple evaluation theory.

### 1. Optimize for page improvement, not conversation volume

The primary test for any Talk Page feature is whether it helps the canonical page become more accurate, more stable, or easier to maintain. A feature that increases posting but does not improve editorial outcomes is probably solving the wrong problem.

Good signals:

- disputed facts get resolved with evidence
- ambiguous editorial decisions are documented
- future editors can understand prior consensus
- stewards notice and engage with meaningful questions

Bad signals:

- the surface fills with opinions, side conversations, or storytelling
- the same questions get asked repeatedly because prior outcomes are hard to find
- contributors discuss issues there that never translate into page improvements

### 2. Preserve a strong distinction between editorial discussion and social discussion

This is the clearest lesson from the landscape. Systems perform better when users can tell whether they are:

- improving the page
- commenting on the page
- discussing the subject broadly
- reporting a discrete issue

This project should evaluate Talk Page features by how well they reinforce that distinction. If a feature blurs the line and invites generic chatter, it is likely hurting the product.

### 3. Favor durable memory over ephemeral exchange

This project's mission is archival. So the highest-value Talk Page features are the ones that create useful records for future editors. A thread that documents why a source was rejected in 2026 may still save time in 2031. A thread full of "great article" reactions will not.

This implies that the best Talk Page features are those that make substantive threads easy to find, revisit, and interpret later.

### 4. Support stewardship without creating ownership

Talk Pages should help contributors act like stewards: noticing changes, answering questions, defending quality, and helping newcomers understand norms. But they should not imply private ownership of pages or create emotional veto power for the first substantial contributor.

Features should therefore reward maintenance and accountability, not territorial control.

### 5. Fit the museum's operating model

This project does not have staff capacity for heavy moderation or intricate workflow management. Talk Page features should be judged partly by whether they can function with a small, mission-aligned community and low operational overhead.

If a feature only works when staff actively triage, close, merge, coach, or mediate threads, it is probably a bad fit for the current stage.

### 6. Be honest about stage risk

An empty or low-traffic Talk Page system can be worse than no system. It signals inactivity and gives users another place to check. This project should evaluate features partly on whether they still make sense at small scale, with a small founding contributor cohort and relatively low disagreement volume.

That argues for a tight initial scope and against broad community-discussion ambitions.

## Features

If this project decides to have Talk Pages, the feature set should be built around the narrow editorial job described above.

### Core features that fit the Talk Page job

- A dedicated discussion space attached to each canonical page, clearly framed as "discussion about improving this page"
- Threaded topics rather than one continuous wall of comments, so distinct issues can be separated
- Clear titles for threads, because archival value depends on future editors being able to scan what was discussed
- Replies and quoting, enough to support back-and-forth on evidence without turning into formatting work
- Attribution and timestamps, so participants can assess context and accountability
- Permalinks to threads or comments, because durable editorial memory needs stable references
- A lightweight way to follow or subscribe to a page or thread, so stewards can notice disputes or questions
- Basic searchability or filterability, because unresolved and prior-resolved issues need to be discoverable
- A visible relationship to the page's edit history, so discussion and page change remain connected in the contributor's mental model

These features support the central business value: lower-friction coordination around page quality.

### Features that may be justified later, but only if the core case proves real

- Marking a thread as resolved or answered
- Highlighting threads that resulted in a substantive page update
- Prompting editors to summarize a discussion outcome in a concise "decision" note
- A lightweight way to surface unresolved evidence requests, such as "needs source" or "question about chronology"
- Notifications when a watched page's Talk Page gets a new thread or reply

These features are useful only if there is enough real editorial use to justify additional workflow.

### Features that do not belong in Talk Pages

- reaction counts as a primary signal
- generic article comments
- reviews, ratings, or "what do you think of this machine?" prompts
- broad community threads untethered from improving the page
- troubleshooting, ownership, repair, pricing, or buying advice discussions
- social feed mechanics designed mainly to maximize participation volume

Those can all be valid products. They are just not Talk Pages in the sense that best serves this project.

### A practical product rule

A useful rule of thumb is this: if a discussion could plausibly end with "and therefore the page should change in this way," it may belong on a Talk Page. If not, it probably belongs somewhere else.

## Conclusion

The landscape does not point toward Talk Pages as a generic engagement feature. It points toward Talk Pages as an editorial maintenance tool.

That is good news for this project, because the business case for editorial maintenance is much stronger than the business case for trying to compete as a general community platform. This project does not need to out-forum Pinside. It needs to become the place where careful pinball knowledge can be built, corrected, and preserved over time.

If this project launches Talk Pages, they should be explicitly positioned as:

- a place to discuss how to improve a page
- a place to resolve disputes about facts, framing, and sources
- a place to preserve editorial memory for future contributors

They should not be positioned as:

- comments on an article
- a general-purpose subject forum
- a social community feed
- a replacement for narrower issue-reporting flows

In product terms, the highest-leverage version of Talk Pages is narrow, evidence-oriented, durable, and steward-friendly. If this project wants that job done, Talk Pages are a strong fit. If what it actually wants is conversation, then it should build for conversation directly rather than smuggling a forum into the encyclopedia under the wrong name.
