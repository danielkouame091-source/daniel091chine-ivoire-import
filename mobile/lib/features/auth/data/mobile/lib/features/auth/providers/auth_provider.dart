import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/auth_repository.dart';
import '../data/models/user.dart';

final authRepositoryProvider = Provider<AuthRepository>(
  (ref) => AuthRepository(ApiClient.publicDio),
);

class AuthState {
  const AuthState({
    this.user,
    this.loading = false,
    this.error,
    this.mfaPending,
    this.sessionToken,
    this.email,
  });

  final User?  user;
  final bool   loading;
  final String? error;
  final bool   mfaPending;
  final String? sessionToken;
  final String? email;

  bool get isAuthenticated => user != null;
  bool get needsMfa        => mfaPending;

  AuthState copyWith({
    User? user,
    bool? loading,
    String? error,
    bool? mfaPending,
    String? sessionToken,
    String? email,
    bool clearError = false,
  }) => AuthState(
        user: user ?? this.user,
        loading: loading ?? this.loading,
        error: clearError ? null : (error ?? this.error),
        mfaPending: mfaPending ?? this.mfaPending,
        sessionToken: sessionToken ?? this.sessionToken,
        email: email ?? this.email,
      );
}

class AuthNotifier extends StateNotifier<AuthState> {
  AuthNotifier(this._repo) : super(const AuthState());
  final AuthRepository _repo;

  Future<void> login(String email, String password) async {
    state = state.copyWith(loading: true, clearError: true);
    try {
      final tokens = await _repo.login(email: email, password: password);

      if (tokens.mfaRequired) {
        state = state.copyWith(
          loading: false,
          mfaPending: true,
          sessionToken: tokens.sessionToken,
          email: email,
        );
        return;
      }

      final user = await _repo.me();
      state = state.copyWith(user: user, loading: false, mfaPending: false);
    } on ApiException catch (e) {
      state = state.copyWith(loading: false, error: e.message);
    } catch (e) {
      state = state.copyWith(loading: false, error: 'Erreur de connexion');
    }
  }

  Future<void> verifyMfa(String code) async {
    if (state.sessionToken == null || state.email == null) return;
    state = state.copyWith(loading: true, clearError: true);
    try {
      await _repo.verifyMfa(
        email: state.email!,
        code: code,
        sessionToken: state.sessionToken!,
      );
      final user = await _repo.me();
      state = state.copyWith(user: user, loading: false, mfaPending: false);
    } on ApiException catch (e) {
      state = state.copyWith(loading: false, error: e.message);
    }
  }

  Future<void> restoreSession() async {
    state = state.copyWith(loading: true);
    try {
      final user = await _repo.me();
      state = state.copyWith(user: user, loading: false);
    } catch (_) {
      state = state.copyWith(loading: false);
    }
  }

  Future<void> logout() async {
    await _repo.logout();
    state = const AuthState();
  }
}

final authProvider = StateNotifierProvider<AuthNotifier, AuthState>(
  (ref) => AuthNotifier(ref.watch(authRepositoryProvider)),
);
