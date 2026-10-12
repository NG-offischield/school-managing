/// Shared components: software identity, async states (loading / error /
/// empty with retry), status chip, message banner.
library;

import 'package:flutter/material.dart';

import '../api/api_error.dart';
import '../theme/app_theme.dart';
import '../l10n/l10n.dart';

const softwareName = 'School Managing';

/// Identity of the SOFTWARE (splash, login, navigation). The official logo
/// (concept 5) is not in the repository yet: the name is shown in text
/// until the official asset is added — no logo is fabricated. School
/// documents never use this mark (they carry the school's branding).
class SoftwareBrand extends StatelessWidget {
  const SoftwareBrand({super.key, this.light = false, this.size = 26, this.subtitle});

  final bool light;
  final double size;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    final color = light ? Colors.white : Tokens.navy;
    return Semantics(
      label: softwareName,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            softwareName,
            style: TextStyle(fontSize: size, fontWeight: FontWeight.w800, color: color, letterSpacing: 0.2),
          ),
          if (subtitle != null)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                subtitle!,
                style: TextStyle(fontSize: 14, color: light ? Colors.white70 : Tokens.textSecondary),
              ),
            ),
        ],
      ),
    );
  }
}

/// Loading / error (with retry) / empty / data, for every screen.
class AsyncBody<T> extends StatelessWidget {
  const AsyncBody({
    super.key,
    required this.future,
    required this.builder,
    required this.onRetry,
    this.isEmpty,
    this.emptyText = 'Rien à afficher pour le moment.',
  });

  final Future<T>? future;
  final Widget Function(BuildContext context, T data) builder;
  final VoidCallback onRetry;
  final bool Function(T data)? isEmpty;
  final String emptyText;

  @override
  Widget build(BuildContext context) {
    // The screen may be gone (session expired, tab closed) before the request
    // ends: the error is then observed here instead of becoming unhandled.
    future?.ignore();
    return FutureBuilder<T>(
      future: future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return Center(child: CircularProgressIndicator(semanticsLabel: tr('Chargement')));
        }
        if (snapshot.hasError) {
          final error = snapshot.error;
          final text = error is ApiException ? error.userMessage : tr('Une erreur inattendue est survenue.');
          return ErrorState(message: text, offline: error is NetworkException, onRetry: onRetry);
        }
        final data = snapshot.data as T;
        if (isEmpty?.call(data) ?? false) return EmptyState(text: tr(emptyText)); // the default is French source
        return builder(context, data);
      },
    );
  }
}

class ErrorState extends StatelessWidget {
  const ErrorState({super.key, required this.message, required this.onRetry, this.offline = false});

  final String message;
  final bool offline;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(offline ? Icons.wifi_off_rounded : Icons.error_outline_rounded, size: 48, color: Tokens.textSecondary),
            const SizedBox(height: 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 16, color: Tokens.text),
            ),
            const SizedBox(height: 16),
            OutlinedButton.icon(onPressed: onRetry, icon: const Icon(Icons.refresh), label: Text(tr('Réessayer'))),
          ],
        ),
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.text, this.icon = Icons.inbox_outlined});

  final String text;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 44, color: Tokens.textSecondary),
            const SizedBox(height: 10),
            Text(
              text,
              textAlign: TextAlign.center,
              style: TextStyle(color: Tokens.textSecondary, fontSize: 15),
            ),
          ],
        ),
      ),
    );
  }
}

enum Tone { neutral, info, success, warning, danger }

class StatusChip extends StatelessWidget {
  const StatusChip(this.label, {super.key, this.tone = Tone.neutral});

  final String label;
  final Tone tone;

  @override
  Widget build(BuildContext context) {
    final (fg, bg) = switch (tone) {
      Tone.info => (Tokens.info, Tokens.infoBg),
      Tone.success => (Tokens.success, Tokens.successBg),
      Tone.warning => (Tokens.warning, Tokens.warningBg),
      Tone.danger => (Tokens.error, Tokens.errorBg),
      Tone.neutral => (Tokens.textSecondary, const Color(0xFFEEF1F5)),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(20)),
      child: Text(
        label,
        style: TextStyle(color: fg, fontWeight: FontWeight.w600, fontSize: 12.5),
      ),
    );
  }
}

class MessageBanner extends StatelessWidget {
  const MessageBanner(this.text, {super.key, this.tone = Tone.danger});

  final String text;
  final Tone tone;

  @override
  Widget build(BuildContext context) {
    final (fg, bg, icon) = switch (tone) {
      Tone.success => (Tokens.success, Tokens.successBg, Icons.check_circle_outline),
      Tone.info => (Tokens.info, Tokens.infoBg, Icons.info_outline),
      Tone.warning => (Tokens.warning, Tokens.warningBg, Icons.warning_amber_rounded),
      _ => (Tokens.error, Tokens.errorBg, Icons.error_outline),
    };
    return Semantics(
      liveRegion: true,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: fg.withValues(alpha: 0.4)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: fg, size: 20),
            const SizedBox(width: 10),
            Expanded(
              child: Text(text, style: TextStyle(color: fg, fontSize: 14.5)),
            ),
          ],
        ),
      ),
    );
  }
}
