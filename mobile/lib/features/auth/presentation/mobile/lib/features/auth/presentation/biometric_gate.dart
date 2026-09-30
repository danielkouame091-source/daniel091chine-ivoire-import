import 'package:flutter/material.dart';
import 'package:local_auth/local_auth.dart';

class BiometricGate extends StatelessWidget {
  const BiometricGate({required this.child, super.key});
  final Widget child;

  Future<bool> _authenticate() async {
    final auth = LocalAuthentication();
    try {
      return await auth.authenticate(
        localizedReason: 'Authentifiez-vous pour accéder à MTech',
        options: const AuthenticationOptions(
          biometricOnly: false,
          stickyAuth: true,
          useErrorDialogs: true,
        ),
      );
    } catch (_) {
      return false;
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<bool>(
      future: _authenticate(),
      builder: (context, snapshot) {
        if (!snapshot.hasData) {
          return const Scaffold(
            body: Center(child: CircularProgressIndicator()),
          );
        }
        if (snapshot.data == true) return child;
        return Scaffold(
          body: Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.fingerprint, size: 64, color: Colors.grey),
                const SizedBox(height: 16),
                const Text('Authentification requise'),
                const SizedBox(height: 16),
                ElevatedButton(
                  onPressed: () async {
                    final ok = await _authenticate();
                    if (ok && context.mounted) {
                      Navigator.of(context).pushReplacement(
                        MaterialPageRoute(builder: (_) => child),
                      );
                    }
                  },
                  child: const Text('Réessayer'),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}
