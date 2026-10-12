import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:school_core/school_core.dart';

import '../data/parent_repository.dart';
import '../models/models.dart';

/// The children the SERVER lets this parent see (verified links only) and
/// the one currently selected. The list is never extended locally.
class ChildScope extends ChangeNotifier {
  ChildScope(this.repository);

  final ParentRepository repository;
  List<Child> children = const [];
  Child? selected;
  bool loaded = false;
  Object? error;

  Future<void> load() async {
    try {
      children = await repository.children();
      error = null;
      final keep = children.where((c) => c.id == selected?.id).firstOrNull;
      selected = keep ?? (children.isEmpty ? null : children.first);
    } on Object catch (e) {
      error = e;
    }
    loaded = true;
    notifyListeners();
  }

  void select(Child child) {
    selected = child;
    notifyListeners();
  }
}

/// Child selector of the app bar (shown when several children are linked).
class ChildSwitcher extends StatelessWidget {
  const ChildSwitcher({super.key});

  @override
  Widget build(BuildContext context) {
    final scope = context.watch<ChildScope>();
    final selected = scope.selected;
    if (selected == null) return const SizedBox.shrink();
    if (scope.children.length < 2) {
      return Padding(
        padding: const EdgeInsets.only(right: 12),
        child: Center(
          child: Text(selected.firstName, style: const TextStyle(fontWeight: FontWeight.w600)),
        ),
      );
    }
    return PopupMenuButton<Child>(
      key: const Key('child.switcher'),
      tooltip: 'Changer d\'enfant',
      onSelected: scope.select,
      itemBuilder: (_) => [
        for (final child in scope.children)
          PopupMenuItem(
            value: child,
            child: Text(child.name, style: TextStyle(fontWeight: child.id == selected.id ? FontWeight.w700 : null)),
          ),
      ],
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(selected.firstName, style: const TextStyle(fontWeight: FontWeight.w600)),
            const Icon(Icons.arrow_drop_down),
          ],
        ),
      ),
    );
  }
}

/// Body of a per-child screen: waits for the children, explains when there
/// is none, otherwise builds for the selected child.
class ChildBody extends StatelessWidget {
  const ChildBody({super.key, required this.builder});

  final Widget Function(BuildContext context, Child child) builder;

  @override
  Widget build(BuildContext context) {
    final scope = context.watch<ChildScope>();
    if (!scope.loaded) return const Center(child: CircularProgressIndicator(semanticsLabel: 'Chargement'));
    final error = scope.error;
    if (error != null) {
      return ErrorState(
        message: error is ApiException ? error.userMessage : 'Une erreur inattendue est survenue.',
        offline: error is NetworkException,
        onRetry: scope.load,
      );
    }
    final child = scope.selected;
    if (child == null) {
      return const EmptyState(
        icon: Icons.family_restroom,
        text: 'Aucun enfant rattaché pour le moment. Faites une demande de rattachement depuis l\'accueil.',
      );
    }
    return builder(context, child);
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle(this.text, {super.key, this.trailing});

  final String text;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(2, 18, 2, 8),
      child: Row(
        children: [
          Expanded(
            child: Text(
              text,
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700, color: Tokens.text),
            ),
          ),
          ?trailing,
        ],
      ),
    );
  }
}

/// Label / value line of a detail card.
class InfoRow extends StatelessWidget {
  const InfoRow(this.label, this.value, {super.key, this.strong = false});

  final String label;
  final String value;
  final bool strong;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Text(label, style: TextStyle(color: Tokens.textSecondary)),
          ),
          const SizedBox(width: 12),
          Flexible(
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: TextStyle(fontWeight: strong ? FontWeight.w700 : FontWeight.w500),
            ),
          ),
        ],
      ),
    );
  }
}

/// Opens [screen] above the shell, keeping the live state (school_core) and
/// the selected child.
Future<T?> openScreen<T>(BuildContext context, Widget screen) => openAbove<T>(
  context,
  screen,
  extra: (context) => [ChangeNotifierProvider<ChildScope>.value(value: context.read<ChildScope>())],
);
