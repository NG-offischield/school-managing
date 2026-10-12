import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../api/api_error.dart';
import '../data/communication.dart';
import '../data/school_plans.dart';
import '../theme/app_theme.dart';
import '../widgets/widgets.dart';
import 'live_state.dart';
import '../l10n/l10n.dart';

/// « Plan de l'établissement » (parent and teacher apps): the published plans
/// the server lets THIS member see — an unauthorised, withdrawn or draft plan
/// simply does not exist here. Images: pinch to zoom, drag to pan, kept in
/// memory only. PDF: shown by the phone's viewer (school_core openDocument),
/// the app keeps no copy of it.
class PlansScreen extends StatefulWidget {
  const PlansScreen({super.key});

  @override
  State<PlansScreen> createState() => _PlansScreenState();
}

class _PlansScreenState extends State<PlansScreen> {
  Future<List<SchoolPlan>>? _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    final future = context.read<CommunicationRepository>().plans();
    setState(() {
      _future = future;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(tr('Plan de l\'établissement'))),
      body: RefreshIndicator(
        onRefresh: () async {
          _load();
          await _future?.catchError((_) => <SchoolPlan>[]);
        },
        child: AsyncBody<List<SchoolPlan>>(
          future: _future,
          onRetry: _load,
          isEmpty: (rows) => rows.isEmpty,
          emptyText: tr('Aucun plan de l\'établissement n\'est disponible pour le moment.'),
          builder: (context, rows) => ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: rows.length,
            separatorBuilder: (_, _) => const SizedBox(height: 10),
            itemBuilder: (context, i) => _PlanCard(plan: rows[i]),
          ),
        ),
      ),
    );
  }
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({required this.plan});

  final SchoolPlan plan;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        key: Key('plan.${plan.id}'),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        leading: Icon(plan.isPdf ? Icons.picture_as_pdf_outlined : Icons.map_outlined, color: Tokens.primary),
        title: Text(plan.title, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (plan.location.isNotEmpty) Text(plan.location),
            Text(
              [
                'Version ${plan.number}',
                if (plan.publishedAt != null) tr('publiée le {0}', [dateOnly.format(plan.publishedAt!)]),
              ].join(' · '),
              style: TextStyle(color: Tokens.textSecondary, fontSize: 13),
            ),
          ],
        ),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => Navigator.of(context).push(
          MaterialPageRoute<void>(
            builder: (_) => PlanViewerScreen(planId: plan.id, plan: plan),
          ),
        ),
      ),
    );
  }
}

/// One plan: its information, then the published file — fetched again from
/// the server each time (access re-checked; a withdrawn plan is « plus
/// disponible »). Also opened from a PLAN notification ([planId] only).
class PlanViewerScreen extends StatefulWidget {
  const PlanViewerScreen({super.key, required this.planId, this.plan});

  final String planId;
  final SchoolPlan? plan;

  @override
  State<PlanViewerScreen> createState() => _PlanViewerScreenState();
}

typedef _Loaded = ({SchoolPlan plan, Uint8List bytes});

class _PlanViewerScreenState extends State<PlanViewerScreen> {
  Future<_Loaded>? _future;
  final _zoom = TransformationController();
  String? _message;
  Tone _tone = Tone.info;
  bool _opening = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _zoom.dispose();
    super.dispose();
  }

  void _load() {
    final repo = context.read<CommunicationRepository>();
    setState(() {
      _message = null;
      _future = () async {
        // The plan is read again: its current version may have changed since the list.
        final plan = await repo.plan(widget.planId);
        return (plan: plan, bytes: await repo.planFile(widget.planId));
      }();
    });
  }

  Future<void> _openPdf(_Loaded loaded) async {
    setState(() => _opening = true);
    final files = context.read<PlanFiles>();
    final safe = loaded.plan.title.replaceAll(RegExp(r'[^A-Za-z0-9]+'), '-');
    final opened = await files.openPdf('plan-$safe-v${loaded.plan.number}.pdf', loaded.bytes);
    if (!mounted) return;
    setState(() {
      _opening = false;
      _tone = opened ? Tone.info : Tone.warning;
      _message = opened
          ? null
          : tr('Aucune application de ce téléphone ne sait afficher les PDF. Installez un lecteur PDF puis réessayez.');
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.plan?.title ?? tr('Plan de l\'établissement')),
        actions: [
          IconButton(
            key: const Key('plan.fit'),
            tooltip: tr('Ajuster à l\'écran'),
            icon: const Icon(Icons.fit_screen_outlined),
            onPressed: () => _zoom.value = Matrix4.identity(),
          ),
        ],
      ),
      body: FutureBuilder<_Loaded>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState != ConnectionState.done) {
            return Center(child: CircularProgressIndicator(semanticsLabel: tr('Chargement du plan')));
          }
          final error = snapshot.error;
          if (error != null) {
            if (error is NotFoundException) {
              return EmptyState(
                icon: Icons.location_off_outlined,
                text: tr('Ce plan n\'est plus disponible : il a été retiré ou ne vous est plus destiné.'),
              );
            }
            return ErrorState(
              message: error is ApiException ? error.userMessage : tr('Une erreur inattendue est survenue.'),
              offline: error is NetworkException,
              onRetry: _load,
            );
          }
          final loaded = snapshot.data!;
          return Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _Header(plan: loaded.plan),
              if (_message != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                  child: MessageBanner(_message!, tone: _tone),
                ),
              Expanded(child: loaded.plan.isImage ? _image(loaded) : _pdf(loaded)),
            ],
          );
        },
      ),
    );
  }

  Widget _image(_Loaded loaded) {
    return ColoredBox(
      color: const Color(0xFFF2F4F7),
      child: InteractiveViewer(
        key: const Key('plan.viewer'),
        transformationController: _zoom,
        minScale: 0.5,
        maxScale: 8,
        boundaryMargin: const EdgeInsets.all(200),
        child: Center(
          child: Image.memory(
            loaded.bytes,
            key: const Key('plan.image'),
            semanticLabel: tr('Plan : {0}', [loaded.plan.title]),
            gaplessPlayback: true,
            errorBuilder: (_, _, _) =>
                EmptyState(icon: Icons.broken_image_outlined, text: tr('L\'image du plan n\'a pas pu être affichée.')),
          ),
        ),
      ),
    );
  }

  Widget _pdf(_Loaded loaded) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.picture_as_pdf_outlined, size: 56, color: Tokens.primary),
            const SizedBox(height: 12),
            Text(loaded.plan.details, style: TextStyle(color: Tokens.textSecondary)),
            const SizedBox(height: 16),
            FilledButton.icon(
              key: const Key('plan.openPdf'),
              onPressed: _opening ? null : () => _openPdf(loaded),
              icon: const Icon(Icons.open_in_new),
              label: Text(tr('Ouvrir le plan (PDF)')),
            ),
            const SizedBox(height: 8),
            Text(
              tr('Le PDF s\'ouvre dans le lecteur du téléphone, où vous pouvez zoomer.'),
              textAlign: TextAlign.center,
              style: TextStyle(color: Tokens.textSecondary, fontSize: 12.5),
            ),
          ],
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.plan});

  final SchoolPlan plan;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(plan.title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
          if (plan.location.isNotEmpty) Text(plan.location),
          Text(
            [
              plan.schoolName,
              tr('version {0}', [plan.number]),
              if (plan.publishedAt != null) tr('publiée le {0}', [dateOnly.format(plan.publishedAt!)]),
            ].where((p) => p.isNotEmpty).join(' · '),
            style: TextStyle(color: Tokens.textSecondary, fontSize: 13),
          ),
          if (plan.description.isNotEmpty) ...[const SizedBox(height: 6), Text(plan.description)],
        ],
      ),
    );
  }
}
