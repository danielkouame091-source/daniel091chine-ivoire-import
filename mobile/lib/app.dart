import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/config/app_theme.dart';
import 'core/network/api_client.dart';
import 'features/auth/presentation/login_screen.dart';
import 'features/auth/presentation/mfa_screen.dart';
import 'features/auth/providers/auth_provider.dart';
import 'features/dashboard/presentation/dashboard_screen.dart';
import 'features/invoices/presentation/invoices_list_screen.dart';
import 'features/scan/presentation/scan_camera_screen.dart';
import 'features/scan/presentation/scan_process_screen.dart';
import 'features/signature/presentation/signature_screen.dart';
import 'features/approvals/presentation/approvals_screen.dart';
import 'shared/widgets/app_shell.dart';

final _rootKey = GlobalKey<NavigatorState>();
final _shellKey = GlobalKey<NavigatorState>();

final _router = GoRouter(
  navigatorKey: _rootKey,
  initialLocation: '/login',
  routes: [
    GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
    GoRoute(path: '/login/mfa', builder: (_, __) => const MfaScreen()),
    ShellRoute(
      navigatorKey: _shellKey,
      builder: (_, __, child) => AppShell(child: child),
      routes: [
        GoRoute(path: '/dashboard', builder: (_, __) => const DashboardScreen()),
        GoRoute(path: '/invoices', builder: (_, __) => const InvoicesListScreen()),
        GoRoute(path: '/approvals', builder: (_, __) => const ApprovalsScreen()),
        GoRoute(path: '/scan', builder: (_, __) => const ScanCameraScreen()),
        GoRoute(
          path: '/scan/process',
          builder: (_, state) => ScanProcessScreen(imagePath: state.extra as String),
        ),
        GoRoute(
          path: '/signature/:docId',
          builder: (_, state) => SignatureScreen(
            documentId: state.pathParameters['docId']!,
            documentNom: (state.extra as String?) ?? 'Document',
          ),
        ),
      ],
    ),
  ],
);

class MTechApp extends ConsumerStatefulWidget {
  const MTechApp({super.key});

  @override
  ConsumerState<MTechApp> createState() => _MTechAppState();
}

class _MTechAppState extends ConsumerState<MTechApp> {
  @override
  void initState() {
    super.initState();
    ApiClient.init();
    Future.microtask(() => ref.read(authProvider.notifier).restoreSession());
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<AuthState>(authProvider, (prev, next) {
      if (next.user == null && prev?.user != null) {
        _router.go('/login');
      }
    });

    return MaterialApp.router(
      title: 'MTech',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      routerConfig: _router,
    );
  }
}
