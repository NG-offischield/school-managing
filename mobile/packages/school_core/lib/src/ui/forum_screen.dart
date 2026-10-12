/// School forum screens shared by the parent, teacher and staff apps
/// (guardians have no forum: the server shows them no space, and their app
/// does not offer the tab). Collective discussions only: private messages and
/// complaints keep their own screens.
///
/// Everything comes from the server: the spaces I belong to, who may start a
/// discussion (no new thread in an announcements-only space), what is locked,
/// what is an announcement (read-only). The app shows its answers and lets
/// the server refuse the rest (403 / 404 / 400 / 409 thread_locked explained).
/// Live: a forum or announcement notification pushed on the WebSocket
/// refreshes the list and the open thread.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_error.dart';
import '../auth/auth_service.dart';
import '../data/communication.dart';
import '../data/forum.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';
import 'live_state.dart';

bool _isForumEvent(Map<String, dynamic> data) =>
    (data['notification_type'] == 'FORUM' || data['notification_type'] == 'ANNOUNCEMENT') &&
    data['payload'] is Map &&
    (data['payload'] as Map)['thread'] != null;

/// Forum tab: my spaces, their discussions (paginated), a new discussion.
class ForumTab extends StatefulWidget {
  const ForumTab({super.key});

  @override
  State<ForumTab> createState() => _ForumTabState();
}

class _ForumTabState extends State<ForumTab> {
  List<ForumSpace> _spaces = const [];
  final List<ForumThread> _threads = [];
  String? _space; // null = all my spaces
  int _page = 0;
  bool _hasNext = false;
  bool _loading = true;
  bool _loadingMore = false;
  ApiException? _error;
  StreamSubscription<Map<String, dynamic>>? _live;

  @override
  void initState() {
    super.initState();
    _reload();
    _live = context.read<LiveState>().notifications.stream.where(_isForumEvent).listen((_) => _reload());
  }

  @override
  void dispose() {
    _live?.cancel();
    super.dispose();
  }

  CommunicationRepository get _repo => context.read<CommunicationRepository>();

  Future<void> _reload() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final spaces = await _repo.forumSpaces();
      final first = await _repo.forumThreads(space: _space);
      if (!mounted) return;
      setState(() {
        _spaces = spaces;
        _threads
          ..clear()
          ..addAll(first.rows);
        _page = 1;
        _hasNext = first.hasNext;
      });
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _more() async {
    if (_loadingMore || !_hasNext) return;
    setState(() => _loadingMore = true);
    try {
      final next = await _repo.forumThreads(space: _space, page: _page + 1);
      if (!mounted) return;
      setState(() {
        _threads.addAll(next.rows.where((t) => _threads.every((have) => have.id != t.id)));
        _page = next.page;
        _hasNext = next.hasNext;
      });
    } on ApiException catch (error) {
      if (mounted) _say(context, error.userMessage);
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  void _filter(String? space) {
    if (space == _space) return;
    _space = space;
    _reload();
  }

  /// Spaces where a member may start a discussion (not announcements-only).
  List<ForumSpace> get _writable => _spaces.where((s) => !s.announcementsOnly).toList();

  Future<void> _newThread() async {
    final created = await openAbove<ForumThread>(context, NewForumThreadScreen(spaces: _writable, initial: _space));
    if (created == null || !mounted) return;
    await _reload();
    if (mounted) await openAbove<void>(context, ForumThreadScreen(threadId: created.id));
  }

  Future<void> _open(ForumThread thread) async {
    await openAbove<void>(context, ForumThreadScreen(threadId: thread.id));
    if (mounted) _reload(); // replies may have moved it to the top
  }

  String _spaceName(String id) => _spaces.where((s) => s.id == id).map((s) => s.name).firstOrNull ?? '';

  @override
  Widget build(BuildContext context) {
    final error = _error;
    Widget body;
    if (_loading && _threads.isEmpty && error == null) {
      body = const Center(child: CircularProgressIndicator());
    } else if (error != null) {
      body = _ErrorState(error: error, onRetry: _reload);
    } else if (_spaces.isEmpty) {
      body = const _Empty(
        icon: Icons.forum_outlined,
        text:
            'Aucun espace de forum ne vous est ouvert pour le moment. L\'établissement les crée et choisit qui y participe.',
      );
    } else {
      body = RefreshIndicator(
        onRefresh: _reload,
        child: ListView(
          key: const Key('forum.threads'),
          padding: const EdgeInsets.fromLTRB(12, 4, 12, 96),
          children: [
            if (_spaces.length > 1)
              SizedBox(
                height: 48,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: ChoiceChip(
                        key: const Key('forum.space.all'),
                        label: const Text('Tous'),
                        selected: _space == null,
                        onSelected: (_) => _filter(null),
                      ),
                    ),
                    for (final s in _spaces)
                      Padding(
                        padding: const EdgeInsets.only(right: 6),
                        child: ChoiceChip(
                          key: Key('forum.space.${s.id}'),
                          label: Text(s.name),
                          selected: _space == s.id,
                          onSelected: (_) => _filter(s.id),
                        ),
                      ),
                  ],
                ),
              ),
            if (_threads.isEmpty)
              const Padding(
                padding: EdgeInsets.only(top: 48),
                child: _Empty(icon: Icons.chat_outlined, text: 'Aucune discussion pour le moment.'),
              ),
            for (final t in _threads)
              Card(
                child: ListTile(
                  key: Key('forum.thread.${t.id}'),
                  leading: Icon(
                    t.isAnnouncement ? Icons.campaign_outlined : (t.isOpen ? Icons.forum_outlined : Icons.lock_outline),
                    color: t.isAnnouncement ? Tokens.primary : Tokens.textSecondary,
                  ),
                  title: Text(t.title, style: const TextStyle(fontWeight: FontWeight.w600)),
                  subtitle: Text(
                    [
                      _spaceName(t.spaceId),
                      t.authorName,
                      if (t.lastPostAt != null) dateTime.format(t.lastPostAt!),
                    ].where((x) => x.isNotEmpty).join(' · '),
                  ),
                  trailing: t.isAnnouncement
                      ? const StatusChip('Annonce', tone: Tone.info)
                      : (t.isOpen ? null : StatusChip(t.statusLabel, tone: Tone.neutral)),
                  onTap: () => _open(t),
                ),
              ),
            if (_hasNext)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: OutlinedButton(
                  key: const Key('forum.more'),
                  onPressed: _loadingMore ? null : _more,
                  child: Text(_loadingMore ? 'Chargement…' : 'Afficher plus de discussions'),
                ),
              ),
          ],
        ),
      );
    }
    return Scaffold(
      body: body,
      floatingActionButton: _writable.isEmpty
          ? null
          : FloatingActionButton.extended(
              key: const Key('forum.new'),
              onPressed: _newThread,
              icon: const Icon(Icons.add_comment_outlined),
              label: const Text('Nouveau sujet'),
            ),
    );
  }
}

/// One discussion: its posts (paginated, reading order), a reply, my posts.
class ForumThreadScreen extends StatefulWidget {
  const ForumThreadScreen({super.key, required this.threadId});

  final String threadId;

  @override
  State<ForumThreadScreen> createState() => _ForumThreadScreenState();
}

class _ForumThreadScreenState extends State<ForumThreadScreen> {
  ForumThread? _thread;
  final List<ForumPost> _posts = [];
  int _page = 0;
  bool _hasNext = false;
  bool _loading = true;
  bool _sending = false;
  ApiException? _error;
  final _reply = TextEditingController();
  StreamSubscription<Map<String, dynamic>>? _live;

  @override
  void initState() {
    super.initState();
    _load();
    _live = context
        .read<LiveState>()
        .notifications
        .stream
        .where((data) => _isForumEvent(data) && (data['payload'] as Map)['thread'] == widget.threadId)
        .listen((_) => _load());
  }

  @override
  void dispose() {
    _live?.cancel();
    _reply.dispose();
    super.dispose();
  }

  CommunicationRepository get _repo => context.read<CommunicationRepository>();

  /// Reloads the discussion and every page already shown.
  Future<void> _load() async {
    setState(() => _error = null);
    try {
      final thread = await _repo.forumThread(widget.threadId);
      final rows = <ForumPost>[];
      var page = 0;
      var hasNext = true;
      while (hasNext && (page == 0 || page < _page)) {
        final next = await _repo.forumPosts(widget.threadId, page: page + 1);
        rows.addAll(next.rows);
        page = next.page;
        hasNext = next.hasNext;
      }
      if (!mounted) return;
      setState(() {
        _thread = thread;
        _posts
          ..clear()
          ..addAll(rows);
        _page = page;
        _hasNext = hasNext;
      });
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _more() async {
    try {
      final next = await _repo.forumPosts(widget.threadId, page: _page + 1);
      if (!mounted) return;
      setState(() {
        _posts.addAll(next.rows.where((p) => _posts.every((have) => have.id != p.id)));
        _page = next.page;
        _hasNext = next.hasNext;
      });
    } on ApiException catch (error) {
      if (mounted) _say(context, error.userMessage);
    }
  }

  Future<void> _send() async {
    final body = _reply.text.trim();
    if (body.isEmpty || _sending) return;
    setState(() => _sending = true);
    try {
      final post = await _repo.replyForum(widget.threadId, body);
      _reply.clear();
      if (!mounted) return;
      setState(() {
        if (!_hasNext) _posts.add(post); // otherwise it shows up with the last page
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      _say(context, error.userMessage);
      // Locked meanwhile (409 thread_locked) or no longer allowed (403): show the server's state.
      if (error is ForbiddenException || error is ConflictException || error is ValidationException) _load();
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  Future<void> _delete(ForumPost post) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Retirer mon message ?'),
        content: const Text('Il sera masqué pour tous les participants.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(context).pop(false), child: const Text('Annuler')),
          FilledButton(
            key: const Key('forum.delete.confirm'),
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Retirer'),
          ),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    try {
      final removed = await _repo.deleteForumPost(post.id);
      if (!mounted) return;
      setState(() {
        final i = _posts.indexWhere((p) => p.id == post.id);
        if (i >= 0) _posts[i] = removed;
      });
    } on ApiException catch (error) {
      if (mounted) _say(context, error.userMessage);
    }
  }

  @override
  Widget build(BuildContext context) {
    final thread = _thread;
    final me = context.watch<AuthService>().identity?.current?.id;
    final error = _error;
    return Scaffold(
      appBar: AppBar(
        title: Text(thread?.title ?? 'Discussion', maxLines: 1, overflow: TextOverflow.ellipsis),
        actions: [
          const LiveIndicator(),
          IconButton(tooltip: 'Actualiser', onPressed: _load, icon: const Icon(Icons.refresh)),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : (thread == null && error != null)
          ? _ErrorState(error: error, onRetry: _load)
          : Column(
              children: [
                if (thread != null && thread.isAnnouncement)
                  const _Banner(
                    key: Key('forum.announcement'),
                    icon: Icons.campaign_outlined,
                    text: 'Annonce de l\'établissement : lecture seule.',
                  ),
                if (thread != null && !thread.isOpen)
                  _Banner(
                    key: const Key('forum.locked'),
                    icon: Icons.lock_outline,
                    text:
                        'Discussion ${thread.statusLabel.toLowerCase()} par l\'établissement'
                        '${thread.statusReason == null || thread.statusReason!.isEmpty ? '' : ' : ${thread.statusReason}'}.',
                  ),
                Expanded(
                  child: RefreshIndicator(
                    onRefresh: _load,
                    child: ListView(
                      key: const Key('forum.posts'),
                      padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
                      children: [
                        for (final p in _posts)
                          Card(
                            key: Key('forum.post.${p.id}'),
                            child: ListTile(
                              title: Text(p.authorName, style: const TextStyle(fontWeight: FontWeight.w600)),
                              subtitle: Padding(
                                padding: const EdgeInsets.only(top: 4),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      p.deleted ? 'Message retiré.' : (p.body ?? ''),
                                      style: TextStyle(
                                        fontStyle: p.deleted ? FontStyle.italic : FontStyle.normal,
                                        color: p.deleted ? Tokens.textSecondary : Tokens.text,
                                      ),
                                    ),
                                    if (p.createdAt != null)
                                      Padding(
                                        padding: const EdgeInsets.only(top: 4),
                                        child: Text(
                                          dateTime.format(p.createdAt!),
                                          style: TextStyle(fontSize: 12, color: Tokens.textSecondary),
                                        ),
                                      ),
                                  ],
                                ),
                              ),
                              trailing: (p.authorId == me && !p.deleted && !p.isAnnouncement)
                                  ? IconButton(
                                      key: Key('forum.delete.${p.id}'),
                                      tooltip: 'Retirer mon message',
                                      icon: const Icon(Icons.delete_outline),
                                      onPressed: () => _delete(p),
                                    )
                                  : null,
                            ),
                          ),
                        if (_hasNext)
                          OutlinedButton(
                            key: const Key('forum.posts.more'),
                            onPressed: _more,
                            child: const Text('Messages suivants'),
                          ),
                      ],
                    ),
                  ),
                ),
                if (thread != null && thread.acceptsReplies)
                  SafeArea(
                    top: false,
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(12, 4, 8, 8),
                      child: Row(
                        children: [
                          Expanded(
                            child: TextField(
                              key: const Key('forum.reply'),
                              controller: _reply,
                              minLines: 1,
                              maxLines: 4,
                              textCapitalization: TextCapitalization.sentences,
                              onChanged: (_) => setState(() {}),
                              decoration: const InputDecoration(hintText: 'Votre réponse'),
                            ),
                          ),
                          IconButton(
                            key: const Key('forum.send'),
                            tooltip: 'Publier',
                            onPressed: _reply.text.trim().isEmpty || _sending ? null : _send,
                            icon: const Icon(Icons.send),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
    );
  }
}

/// New discussion in one of the spaces where I may write.
class NewForumThreadScreen extends StatefulWidget {
  const NewForumThreadScreen({super.key, required this.spaces, this.initial});

  final List<ForumSpace> spaces;
  final String? initial;

  @override
  State<NewForumThreadScreen> createState() => _NewForumThreadScreenState();
}

class _NewForumThreadScreenState extends State<NewForumThreadScreen> {
  late String? _space = widget.spaces.any((s) => s.id == widget.initial)
      ? widget.initial
      : (widget.spaces.length == 1 ? widget.spaces.single.id : null);
  final _title = TextEditingController();
  final _body = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _title.dispose();
    _body.dispose();
    super.dispose();
  }

  bool get _ready => _space != null && _title.text.trim().isNotEmpty && _body.text.trim().isNotEmpty && !_busy;

  Future<void> _submit() async {
    if (!_ready) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final thread = await context.read<CommunicationRepository>().createForumThread(
        space: _space!,
        title: _title.text,
        body: _body.text,
      );
      if (mounted) Navigator.of(context).pop(thread);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error.userMessage);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Nouveau sujet')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            'Une discussion visible par les membres de l\'espace choisi. Pour une question personnelle, utilisez '
            'plutôt les messages privés.',
            style: TextStyle(color: Tokens.textSecondary),
          ),
          const SizedBox(height: 14),
          if (_error != null) ...[MessageBanner(_error!), const SizedBox(height: 12)],
          DropdownButtonFormField<String>(
            key: const Key('forum.new.space'),
            initialValue: _space,
            decoration: const InputDecoration(labelText: 'Espace'),
            items: [for (final s in widget.spaces) DropdownMenuItem(value: s.id, child: Text(s.name))],
            onChanged: (value) => setState(() => _space = value),
          ),
          const SizedBox(height: 12),
          TextField(
            key: const Key('forum.new.title'),
            controller: _title,
            maxLength: 200,
            textCapitalization: TextCapitalization.sentences,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(labelText: 'Titre'),
          ),
          TextField(
            key: const Key('forum.new.body'),
            controller: _body,
            minLines: 4,
            maxLines: 10,
            textCapitalization: TextCapitalization.sentences,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(labelText: 'Message'),
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            key: const Key('forum.new.submit'),
            onPressed: _ready ? _submit : null,
            icon: const Icon(Icons.send),
            label: Text(_busy ? 'Publication…' : 'Publier'),
          ),
        ],
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({super.key, required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    color: Tokens.infoBg,
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
    child: Row(
      children: [
        Icon(icon, color: Tokens.info),
        const SizedBox(width: 10),
        Expanded(child: Text(text)),
      ],
    ),
  );
}

class _Empty extends StatelessWidget {
  const _Empty({required this.icon, required this.text});

  final IconData icon;
  final String text;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 40, color: Tokens.textSecondary),
          const SizedBox(height: 10),
          Text(
            text,
            textAlign: TextAlign.center,
            style: TextStyle(color: Tokens.textSecondary),
          ),
        ],
      ),
    ),
  );
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.error, required this.onRetry});

  final ApiException error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          MessageBanner(
            error is NotFoundException
                ? 'Cette discussion n\'existe plus ou ne vous est pas accessible.'
                : error is ForbiddenException
                ? 'Le forum de cet espace ne vous est pas accessible.'
                : error.userMessage,
          ),
          const SizedBox(height: 12),
          OutlinedButton(key: const Key('forum.retry'), onPressed: onRetry, child: const Text('Réessayer')),
        ],
      ),
    ),
  );
}

void _say(BuildContext context, String text) =>
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
