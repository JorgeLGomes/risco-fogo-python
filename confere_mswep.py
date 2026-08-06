# Confere um arquivo MSWEP real: variável, grade e recorte do domínio
import sys, time, rf_core, rf_config
caminho = sys.argv[1]
la, lo = rf_core.le_grade_precip(caminho)                       # grade completa
print(f"grade do arquivo : {la.size} x {lo.size}  "
      f"(lat {la[0]:.2f}..{la[-1]:.2f}, lon {lo[0]:.2f}..{lo[-1]:.2f})")
dom = rf_config.recorte_precipitacao({"fonte": "mswep", "modo": "in_loco"})
t0 = time.time()
d, la, lo = rf_core.le_precip_arquivo(caminho, None, dom)
print(f"recorte {dom}  ->  {d.shape[1]} x {d.shape[2]} pontos "
      f"em {time.time()-t0:.2f}s")
print(f"lat {la[0]:.2f}..{la[-1]:.2f}   lon {lo[0]:.2f}..{lo[-1]:.2f}")
