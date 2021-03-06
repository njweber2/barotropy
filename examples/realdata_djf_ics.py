# -*- coding: utf-8 -*-

from barotropy import (
    LinearizedDynamics, LinearizedDiffusion, LinearizedDamping, Forcing,
    NonlinearDynamics, NonlinearDiffusion, NonlinearDamping,
    from_u_and_v_winds, debug_plots
)
from sympl import (Leapfrog, PlotFunctionMonitor, NetCDFMonitor, TendencyInDiagnosticsWrapper,
                   get_component_aliases, get_constant)
from datetime import timedelta
import re
import os
import numpy as np
from time import time
from netCDF4 import Dataset

Re = get_constant('planetary_radius', 'm')
Omega = get_constant('planetary_rotation_rate', 's^-1')

# ============ Adjustable Variables ============
# Integration Options
dt = timedelta(minutes=15)  # timestep
duration = '10_00:00'       # run duration ('<days>_<hours>:<mins>')t
linearized = True          # run model using linearized state/equations?
ncout_freq = 6              # netcdf write frequency (hours)
plot_freq = 6               # plot Monitor call frequency (hours)
ntrunc = 42                 # triangular truncation for spharm (e.g., 21 --> T21)

# Diffusion Options
diff_on = True              # Use diffusion?
k = 2.338e16                # Diffusion coefficient for del^4 hyperdiffusion

# Forcing Options
forcing_on = True           # Apply vort. tendency forcing?
damp_ts = 14.7               # Damping timescale (in days)

# I/O Options
ncoutfile = os.path.join(os.path.dirname(__file__), 'realdata.nc')
append_nc = False            # Append to an existing netCDF file?
# ==============================================

start = time()

# Get the initial state
ic_file = os.path.join(os.path.dirname(__file__), 'cfs_djf_ics.nc')
with Dataset(ic_file, 'r') as ncdata:
    lats = ncdata.variables['latitude'][:]
    lons = ncdata.variables['longitude'][:]
    ubar = ncdata.variables['U200'][:, :]
    vbar = ncdata.variables['V200'][:, :]
uprime = np.zeros(ubar.shape)
vprime = np.zeros(vbar.shape)
state = from_u_and_v_winds(lats, lons, ubar, vbar, uprime, vprime,
                           linearized=linearized, ntrunc=ntrunc)

# Get our Gaussian RWS forcing
centerlocs = [(35., 160.), (35., 100.)]
amplitudes = [4e-10, -4e-10]
widths = [7, 7]
forcing_prog = Forcing.gaussian_tendencies(state['latitude'].values, state['longitude'].values,
                                           centerlocs=centerlocs, amplitudes=amplitudes, widths=widths,
                                           ntrunc=ntrunc, linearized=linearized)

# Set up the Timestepper with the desired Prognostics
if linearized:
    dynamics_prog = LinearizedDynamics(ntrunc=ntrunc)
    diffusion_prog = LinearizedDiffusion(k=k, ntrunc=ntrunc)
    damping_prog = LinearizedDamping(tau=damp_ts)
else:
    dynamics_prog = NonlinearDynamics(ntrunc=ntrunc)
    diffusion_prog = NonlinearDiffusion(k=k, ntrunc=ntrunc)
    damping_prog = NonlinearDamping(tau=damp_ts)
prognostics = [TendencyInDiagnosticsWrapper(dynamics_prog, 'dynamics')]

# Add diffusion
if diff_on:
    prognostics.append(TendencyInDiagnosticsWrapper(diffusion_prog, 'diffusion'))
# Add our forcing
if forcing_on:
    # Get our suptropical RWS forcing (from equatorial divergence)
    prognostics.append(TendencyInDiagnosticsWrapper(forcing_prog, 'forcing'))
    prognostics.append(TendencyInDiagnosticsWrapper(damping_prog, 'damping'))

# Create Timestepper
stepper = Leapfrog(prognostics)

# Create Monitors for plotting & storing data
plt_monitor = PlotFunctionMonitor(debug_plots.fourpanel)
if os.path.isfile(ncoutfile) and not append_nc:
    os.remove(ncoutfile)
aliases = get_component_aliases(*prognostics)
nc_monitor = NetCDFMonitor(ncoutfile, write_on_store=True, aliases=aliases)

# Figure out the end date of this run
d, h, m = re.split('[_:]', duration)
end_date = state['time'] + timedelta(days=int(d), hours=int(h), minutes=int(m))

# Begin the integration loop
idate = state['time']
while state['time'] <= end_date:

    # Get the state at the next timestep using our Timestepper
    diagnostics, next_state = stepper(state, dt)

    # Add any calculated diagnostics to our current state
    state.update(diagnostics)

    # Write state to netCDF every <ncout_freq> hours
    fhour = (state['time'] - idate).days*24 + (state['time'] - idate).seconds/3600
    if fhour % ncout_freq == 0:
        print(state['time'])
        nc_monitor.store(state)

    # Make plot(s) every <plot_freq> hours
    if fhour % plot_freq == 0:
        plt_monitor.store(state)

    # Advance the state to the next timestep
    next_state['time'] = state['time'] + dt
    state = next_state

print('TOTAL INTEGRATION TIME: {:.02f} min\n'.format((time()-start)/60.))
