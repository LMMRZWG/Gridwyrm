"""One module per feature, each given the application and nothing else.

A feature owns its own state and builds its own card in the panel. What it
borrows from the application is the shared grid state, the overlay, and the
styling, all reached through `self.app`. That coupling is deliberate and
one-directional: the application knows a feature exists and calls it, and a
feature never reaches into another feature.
"""
