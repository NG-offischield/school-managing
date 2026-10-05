import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../../data/teacher_repository.dart';
import '../common.dart';
import '../home/home_shell.dart';
import 'conversation_screen.dart';

/// Notifications, messages and complaints visible to the teacher (existing
/// communication API; new notifications arrive live through the WebSocket).
class CommunicationScreen extends StatelessWidget {
  const CommunicationScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final connection = context.watch<LiveState>().connection;
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Communication'),
          actions: [
            if (connection == RealtimeState.online)
              const Padding(
                padding: EdgeInsets.only(right: 14),
                child: Tooltip(message: 'Temps réel connecté', child: Icon(Icons.wifi_tethering, size: 20)),
              )
            else if (connection == RealtimeState.offline)
              const Padding(
                padding: EdgeInsets.only(right: 14),
                child: Tooltip(message: 'Hors ligne : reconnexion automatique', child: Icon(Icons.wifi_off, size: 20)),
              ),
          ],
          bottom: const TabBar(
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white70,
            indicatorColor: Colors.white,
            tabs: [
              Tab(text: 'Notifications'),
              Tab(text: 'Messages'),
              Tab(text: 'Réclamations'),
            ],
          ),
        ),
        body: const TabBarView(children: [NotificationsTab(), ConversationsTab(), ComplaintsTab()]),
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
      _future = context.read<TeacherRepository>().notifications().then((rows) => _rows = rows)..ignore();
    });
  }

  Future<void> _open(AppNotification notification) async {
    final repo = context.read<TeacherRepository>();
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
          ],
        ),
      ),
    );
  }

  Future<void> _markAll() async {
    try {
      await context.read<TeacherRepository>().markAllRead();
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
  const ConversationsTab({super.key});

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
    _future = context.read<TeacherRepository>().conversations()..ignore();
  });

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => _load(),
      child: AsyncBody<List<Conversation>>(
        future: _future,
        onRetry: _load,
        isEmpty: (rows) => rows.isEmpty,
        emptyText: 'Aucune conversation.',
        builder: (context, rows) => ListView(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
          children: [
            for (final c in rows)
              Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  leading: const CircleAvatar(
                    backgroundColor: Tokens.primarySoft,
                    child: Icon(Icons.forum_outlined, color: Tokens.primary),
                  ),
                  title: Text(c.label, style: TextStyle(fontWeight: c.unread > 0 ? FontWeight.w700 : FontWeight.w500)),
                  subtitle: Text(
                    c.lastMessageAt == null ? c.participants.join(', ') : dateTime.format(c.lastMessageAt!),
                  ),
                  trailing: c.unread > 0 ? Badge(label: Text('${c.unread}')) : const Icon(Icons.chevron_right),
                  onTap: () async {
                    // The route sits above the shell: its live state is provided again.
                    final live = context.read<LiveState>();
                    await Navigator.of(context).push(
                      MaterialPageRoute(
                        builder: (_) => ChangeNotifierProvider<LiveState>.value(
                          value: live,
                          child: ConversationScreen(conversation: c),
                        ),
                      ),
                    );
                    _load();
                  },
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class ComplaintsTab extends StatefulWidget {
  const ComplaintsTab({super.key});

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
    _future = context.read<TeacherRepository>().complaints()..ignore();
  });

  Tone _tone(String status) => switch (status) {
    'OPEN' => Tone.warning,
    'IN_PROGRESS' => Tone.info,
    'RESOLVED' || 'CLOSED' => Tone.success,
    _ => Tone.neutral,
  };

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async => _load(),
      child: AsyncBody<List<Complaint>>(
        future: _future,
        onRetry: _load,
        isEmpty: (rows) => rows.isEmpty,
        emptyText: 'Aucune réclamation ne vous concerne.',
        builder: (context, rows) => ListView(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
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
    );
  }
}
