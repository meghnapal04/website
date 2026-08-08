import matplotlib.pyplot as plt

# Set global font parameters
plt.rcParams['font.sans-serif'] = 'Helvetica'
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['axes.edgecolor'] = '#CBD5E1'
plt.rcParams['axes.linewidth'] = 0.8

# -------------------------------------------------------------
# FIGURE 1: Dutch Budget Deficit Trajectory (2025-2028)
# -------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6), dpi=300)
fig.patch.set_facecolor('#FFFFFF')
ax.set_facecolor('#FFFFFF')

years = ['2025', '2026', '2027', '2028']
deficit = [-1.6, -3.3, -2.6, -2.3]
colors = ['#2E7D4F', '#C44527', '#2E7D4F', '#2E7D4F']

# Plot bars
bars = ax.bar(years, deficit, color=colors, width=0.45, zorder=3)

# Draw Maastricht reference line
ax.axhline(y=-3.0, color='#C44527', linestyle='--', linewidth=1.8, label='Maastricht Deficit Limit (3.0%)', zorder=4)

# Title and subtitle with clean spacing
fig.text(0.125, 0.94, 'Figure 1: Dutch Budget Deficit Trajectory (2025–2028)', fontsize=15, fontweight='bold', color='#1A202C')
fig.text(0.125, 0.89, "Source: Author's calculations using data from DNB Spring 2026 Outlook", fontsize=10, fontstyle='italic', color='#64748B')

# Axis formatting
ax.set_ylabel('Deficit (% of GDP)', fontsize=11, fontweight='bold', color='#1A202C')
ax.set_ylim(-4.0, 0.5)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.grid(axis='y', linestyle=':', alpha=0.6, color='#E2E8F0', zorder=1)

# Add data labels below bars
for bar in bars:
    yval = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2.0, yval - 0.22, f'{yval:.1f}%', ha='center', va='top', fontsize=10, fontweight='bold', color='#1A202C')

# Custom Legend
ax.legend(loc='upper right', frameon=True, facecolor='#FFFFFF', edgecolor='#E2E8F0', fontsize=10)

plt.tight_layout()
plt.subplots_adjust(top=0.82, bottom=0.12)
plt.savefig('/Users/meghna/Desktop/Meghna Pal Website/Figure_1_Dutch_Budget_Deficit_Trajectory.jpg', format='jpg', dpi=300)
plt.savefig('/Users/meghna/.gemini/antigravity/brain/ae24cbe1-1d27-4efc-b8d5-d6ac9911399c/Figure_1_Dutch_Budget_Deficit_Trajectory.jpg', format='jpg', dpi=300)
plt.close()

# -------------------------------------------------------------
# FIGURE 2: Dutch Government Debt Trajectory (2025-2028)
# -------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6), dpi=300)
fig.patch.set_facecolor('#FFFFFF')
ax.set_facecolor('#FFFFFF')

debt = [44.4, 47.4, 48.4, 49.2]

# Plot Line and Points
ax.plot(years, debt, color='#1B3A6B', linewidth=3, marker='o', markersize=8, markerfacecolor='#1B3A6B', markeredgecolor='#FFFFFF', markeredgewidth=2, label='Government Debt (% of GDP)', zorder=3)
ax.fill_between(years, debt, alpha=0.08, color='#1B3A6B', zorder=2)

# Draw Maastricht Debt Ceiling reference line
ax.axhline(y=60.0, color='#9E9890', linestyle='--', linewidth=1.8, label='Maastricht Debt Ceiling (60.0%)', zorder=4)

# Title and subtitle with clean spacing
fig.text(0.125, 0.94, 'Figure 2: Dutch Government Debt Trajectory (2025–2028)', fontsize=15, fontweight='bold', color='#1A202C')
fig.text(0.125, 0.89, "Source: Author's calculations using data from DNB Spring 2026 Outlook", fontsize=10, fontstyle='italic', color='#64748B')

# Axis formatting
ax.set_ylabel('Debt (% of GDP)', fontsize=11, fontweight='bold', color='#1A202C')
ax.set_ylim(35.0, 65.0)
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.grid(axis='y', linestyle=':', alpha=0.6, color='#E2E8F0', zorder=1)

# Add data labels next to points
for i, txt in enumerate(debt):
    ax.annotate(f'{txt:.1f}%', (years[i], debt[i]), textcoords="offset points", xytext=(0, 10), ha='center', fontsize=10, fontweight='bold', color='#1B3A6B')

# Custom Legend
ax.legend(loc='upper right', frameon=True, facecolor='#FFFFFF', edgecolor='#E2E8F0', fontsize=10)

plt.tight_layout()
plt.subplots_adjust(top=0.82, bottom=0.12)
plt.savefig('/Users/meghna/Desktop/Meghna Pal Website/Figure_2_Dutch_Government_Debt_Trajectory.jpg', format='jpg', dpi=300)
plt.savefig('/Users/meghna/.gemini/antigravity/brain/ae24cbe1-1d27-4efc-b8d5-d6ac9911399c/Figure_2_Dutch_Government_Debt_Trajectory.jpg', format='jpg', dpi=300)
plt.close()

print('Updated JPEG graphs generated with clean typography alignment!')
