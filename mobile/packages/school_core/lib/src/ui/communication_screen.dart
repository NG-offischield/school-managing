import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../api/api_error.dart';
import '../data/communication.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';
import 'composers.dart';
import 'conversation_screen.dart';
import 'forum_screen.dart';
import 'live_state.dart';
import 'plans_screen.dart';

/// Notifications, messages and complaints of the parent (existing
/// communication API; new notifications arrive live through the WebSocket).
/// Opens a composer and returns what it created (or null).
typedef Composer<T> = Future<T?> Function(BuildContext context);

/// Notifications, and — only for the roles the server lets use them —
/// messages, complaints and the school forum (spec §8: guardians have no
/// messaging and no forum; complaints are filed by parents and teachers).
/// Forum (collective) and messages (private) stay separate tabs. The server
/// re-checks every action.
class CommunicationScreen extends StatelessWidget {
  const CommunicationScreen({
    super.key,
    this.messaging = true,
    this.complaints = true,
    this.forum = false,
    this.composeConversation,
    this.composeComplaint,
  });

  final bool messaging;
  final bool complaints;

  /// The school forum (parents, teachers, staff); off by default (guardians).
  final bool forum;

  /// New conversation; default: a message to the administration.
  final Composer<Conversation>? composeConversation;

  /// New complaint; default: a complaint without pupil.
  final Composer<Complaint>? composeComplaint;

  @override
  Widget build(BuildContext context) {
    final tabs = <(String, Widget)>[
      ('Notifications', const NotificationsTab()),
      if (messaging)
        (
          'Messages',
          ConversationsTab(
            compose: composeConversation ?? (c) => openAbove<Conversation>(c, const AdminMessageScreen()),
          ),
        ),
      if (complaints)
        (
          'Réclamations',
          ComplaintsTab(compose: composeComplaint ?? (c) => openAbove<Complaint>(c, const ComplaintComposer())),
        ),
      if (forum) ('Forum', const ForumTab()),
    ];
    if (tabs.length == 1) {
      return Scaffold(
        appBar: AppBar(title: const Text('Notifications'), actions: const [LiveIndicator()]),
        body: tabs.single.$2,
      );
    }
    return DefaultTabController(
      length: tabs.length,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Communication'),
          actions: const [LiveIndicator()],
          bottom: TabBar(
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white70,
            indicatorColor: Colors.white,
            tabs: [for (final (label, _) in tabs) Tab(text: label)],
          ),
        ),
        body: TabBarView(children: [for (final (_, body) in tabs) body]),
      ),
    );
  }
}

class NotificationsTab extends StatefulWidget {
  const NotificationsTab({super.key});

  @override
  State<NotificationsTab> createState() => _NotificationsTabState();
}

class _NotificationsTabState extends State<NotificationsTab> {
  Future<List<AppNotification>>? _future;
  List<AppNotification> _rows = [];
  StreamSubscription<Map<String, dynamic>>? _live;

  @override
  void initState() {
    super.initState();
    _load();
    _live = context.read<LiveState>().notifications.stream.listen((data) {
      final pushed = AppNotification.fromJson(data);
      if (_rows.every((n) => n.id != pushed.id)) setState(() => _rows = [pushed, ..._rows]);
    });
  }

  @override
  void dispose() {
    _live?.cancel();
    super.dispose();
  }

  void _load() {
    setState(() {
      _future = context.read<CommunicationRepository>().notifications().then((rows) => _rows = rows)..ignore();
    });
  }

  Future<void> _open(AppNotification notification) async {
    final repo = context.read<CommunicationRepository>();
    final live = context.read<LiveState>();
    if (!notification.read) {
      try {
        await repo.markRead(notification.id);
        setState(() => _rows = [for (final n in _rows) n.id == notification.id ? n.markedRead() : n]);
        live.setUnread((live.unread - 1).clamp(0, 1 << 30));
      } on ApiException catch (error) {
        if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.userMessage)));
      }
    }
    if (!mounted) return;
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (_) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 0, 20, 28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            StatusChip(notification.typeLabel, tone: Tone.info),
            const SizedBox(height: 10),
            Text(notification.title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Text(notification.message, style: const TextStyle(fontSize: 15)),
            const SizedBox(height: 10),
            if (notification.at != null)
              Text(dateTime.format(notification.at!), style: const TextStyle(color: Tokens.textSecondary)),
            if (notification.threadId != null) ...[
              const SizedBox(height: 16),
              FilledButton.icon(
                key: const Key('notification.thread'),
                onPressed: () {
                  Navigator.of(context).pop();
                  openAbove<void>(context, ForumThreadScreen(threadId: notification.threadId!));
                },
                icon: const Icon(Icons.forum_outlined),
                label: const Text('Ouvrir la discussion'),
              ),
            ],
            if (notification.planId != null) ...[
              const SizedBox(height: 16),
              FilledButton.icon(
                key: const Key('notification.plan'),
                onPressed: () {
                  Navigator.of(context).pop();
                  openAbove<void>(context, PlanViewerScreen(planId: notification.planId!));
                },
                icon: const Icon(Icons.map_outlined),
                label: const Text('Ouvrir le plan'),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Future<void> _markAll() async {
    try {
      await context.read<CommunicationRepository>().markAllRead();
      if (!mounted) return;
      context.read<LiveState>().setUnread(0);
      setState(() => _rows = [for (final n in _rows) n.markedRead()]);
    } on ApiException catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.userMessage)));
    }
  }

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => _load(),
      child: AsyncBody<List<AppNotification>>(
        future: _future,
        onRetry: _load,
        isEmpty: (_) => _rows.isEmpty,
        emptyText: 'Aucune notification.',
        builder: (context, _) => ListView(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
          children: [
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: _markAll,
                icon: const Icon(Icons.done_all),
                label: const Text('Tout marquer comme lu'),
              ),
            ),
            for (final n in _rows)
              Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  onTap: () => _open(n),
                  leading: Icon(
                    n.read ? Icons.notifications_none : Icons.notifications_active,
                    color: n.read ? Tokens.textSecondary : Tokens.primary,
                  ),
                  title: Text(n.title, style: TextStyle(fontWeight: n.read ? FontWeight.w500 : FontWeight.w700)),
                  subtitle: Text('${n.typeLabel}${n.at == null ? '' : ' · ${dateTime.format(n.at!)}'}'),
                  trailing: n.read ? null : const StatusChip('Non lue', tone: Tone.info),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class ConversationsTab extends StatefulWidget {
  const ConversationsTab({super.key, required this.compose});

  final Composer<Conversation> compose;

  @override
  State<ConversationsTab> createState() => _ConversationsTabState();
}

class _ConversationsTabState extends State<ConversationsTab> {
  Future<List<Conversation>>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() => setState(() {
    _future = context.read<CommunicationRepository>().conversations()..ignore();
  });

  Future<void> _new() async {
    final created = await widget.compose(context);
    if (created == null || !mounted) return;
    _load();
    await openAbove<void>(context, ConversationScreen(conversation: created));
    if (mounted) _load();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('conversations.new'),
        heroTag: 'conversations.new',
        onPressed: _new,
        icon: const Icon(Icons.edit_outlined),
        label: const Text('Écrire'),
      ),
      body: RefreshIndicator(
        onRefresh: () async => _load(),
        child: AsyncBody<List<Conversation>>(
          future: _future,
          onRetry: _load,
          isEmpty: (rows) => rows.isEmpty,
          emptyText: 'Aucune conversation. Écrivez à l\'administration ou à un enseignant de votre enfant.',
          builder: (context, rows) => ListView(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 88),
            children: [
              for (final c in rows)
                Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: ListTile(
                    leading: CircleAvatar(
                      backgroundColor: Tokens.primarySoft,
                      child: Icon(
                        c.type == 'ADMINISTRATION' ? Icons.apartment_outlined : Icons.forum_outlined,
                        color: Tokens.primary,
                      ),
                    ),
                    title: Text(
                      c.label,
                      style: TextStyle(fontWeight: c.unread > 0 ? FontWeight.w700 : FontWeight.w500),
                    ),
                    subtitle: Text(
                      c.lastMessageAt == null ? c.participants.join(', ') : dateTime.format(c.lastMessageAt!),
                    ),
                    trailing: c.unread > 0 ? Badge(label: Text('${c.unread}')) : const Icon(Icons.chevron_right),
                    onTap: () async {
                      await openAbove<void>(context, ConversationScreen(conversation: c));
                      _load();
                    },
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class ComplaintsTab extends StatefulWidget {
  const ComplaintsTab({super.key, required this.compose});

  final Composer<Complaint> compose;

  @override
  State<ComplaintsTab> createState() => _ComplaintsTabState();
}

class _ComplaintsTabState extends State<ComplaintsTab> {
  Future<List<Complaint>>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() => setState(() {
    _future = context.read<CommunicationRepository>().complaints()..ignore();
  });

  Tone _tone(String status) => switch (status) {
    'OPEN' => Tone.warning,
    'IN_PROGRESS' => Tone.info,
    'RESOLVED' || 'CLOSED' => Tone.success,
    _ => Tone.neutral,
  };

  Future<void> _new() async {
    final created = await widget.compose(context);
    if (created != null && mounted) {
      showMessage(context, 'Réclamation transmise à l\'établissement.');
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('complaints.new'),
        heroTag: 'complaints.new',
        onPressed: _new,
        icon: const Icon(Icons.report_outlined),
        label: const Text('Réclamation'),
      ),
      body: RefreshIndicator(
        onRefresh: () async => _load(),
        child: AsyncBody<List<Complaint>>(
          future: _future,
          onRetry: _load,
          isEmpty: (rows) => rows.isEmpty,
          emptyText: 'Aucune réclamation.',
          builder: (context, rows) => ListView(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 88),
            children: [
              for (final c in rows)
                Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: ExpansionTile(
                    title: Text(c.subject, style: const TextStyle(fontWeight: FontWeight.w600)),
                    subtitle: Text(c.at == null ? '' : dateTime.format(c.at!)),
                    trailing: StatusChip(c.statusLabel, tone: _tone(c.status)),
                    childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                    children: [Align(alignment: Alignment.centerLeft, child: Text(c.description))],
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
