"""Monitor launcher; configuration is scoped to this suite."""
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-check', action='store_true')
    options = parser.parse_args()
    from .xrd_map_gui import XRDMapGUI
    app = XRDMapGUI()
    if options.smoke_check:
        app.after(500, app.destroy)
    app.mainloop()
