#!/bin/bash 

# Risco de fogo previsto de 1km utilizando a temperatura, umidade relativa e a precipitação do GFS.

# Tempo total de execução: aproximadamente 3h00.
# Adaptação por Pedro Lagden para rodar na maquina: popore.met.inpe.br

datainicial=`date +%s` # Cálculo inicial para saber o tempo de máquina utilizado. NÃO DELETAR ESSA LINHA!
#########################################################################################################

data_final=`date +"%Y%m%d"` # Data final do intervalo. Por exemplo, YYYMMDD.
data_inicial=`date +"%Y%m%d" -d "${data_final} 119 days ago "`
data_modelo=`date +"%Y%m%d" -d "${data_final}"`"00"
#data_previsao=`date +"%Y%m%d" -d "${data_final} 14 days "`"18"
data_previsao=`date +"%Y%m%d" -d "${data_final} 14 days "`"18"

# Utilizado para consertar a data do arquivo NetCDF.
ano=${data_final:0:4}

# Usado para definir o ano do mapa de vegetação que tem disponibilidade desde 2001 até 2016.
if [ ${ano} -ge "2020" ]
then
   ano_mapa_veg="2019"
else
   ano_mapa_veg=${ano}
fi

dirin_gfs="/home/queimadas/INPE_FireRiskModel/data/output/2.2/GFS/netcdf/${data_modelo}"                # Previsão do GFS de Temperatura (K), Umidade Relativa (%) e precipitação (mm/dia).
dirin_imerg="/home/queimadas/INPE_FireRiskModel/data/output/2.2/Precipitation-2_2"                              # Dado observado de precipitação do IMERG (mm/dia).
dir_output_netcdf="/home/queimadas/INPE_FireRiskModel/data/output/2.2/RF_PREV_SEMANAL/netcdf/${data_modelo}"    # Diretório de saída das previsões no formato NetCDF do RF previsto.
dir_output_tif="/home/queimadas/INPE_FireRiskModel/data/output/2.2/RF_PREV_SEMANAL/tif/${data_modelo}"          # Diretório de saída das previsões no formato tif do RF previsto.
tmp="/home/queimadas/INPE_FireRiskModel/tmp"                                                            # Diretório temporário para executar os scripts.
dir_log="/home/queimadas/INPE_FireRiskModel/log"                                                        # Arquivo log para verificação de erros.
log_file="${dir_log}/RF.PREV.${data_modelo}.arquivos.faltantes.txt"                                             # Nome do arquivo de log para o caso de arquivos faltantes.
DIR_BIN="/home/queimadas/miniconda3/envs/ncl_stable/bin"
export PROJ_DATA="/home/queimadas/miniconda3/envs/ncl_stable/share/proj"

mkdir -p ${dir_output_netcdf}
mkdir -p ${dir_output_tif}

echo "inicio: >>>"${data_inicial}
echo "fim: >>>>>>"${data_final}
echo "modelo: >>>"$data_modelo
echo "ult prev: >>>>>>"$data_previsao

export LANG=en_US.UTF-8

while [ ${data_inicial} -lt ${data_final} ]; do

# Nome do arquivo de precipitação do IMERG.
arquivo_prec_imerg="INPE_FireRiskModel_2.2_Precipitation_${data_inicial}.nc"

dia=${data_inicial:6:2}
mes=${data_inicial:4:2}
ano=${data_inicial:0:4}
 
# Verifica se os arquivos do IMERG existem antes de escrever o nome deles no ".txt"
  if [ -e ${dirin_imerg}/$ano/$mes/${arquivo_prec_imerg} ] ; then
     echo ${dirin_imerg}/$ano/$mes/${arquivo_prec_imerg} >> ${tmp}/arquivo.prev.prec.tmp
  else
     echo ${dirin_imerg}/${arquivo_prec_imerg} >> log.falta.arquivos.prev.prec.txt 
  fi

   data_inicial=`date +"%Y%m%d" -d "${data_inicial} 1 day "`
done

#data_prazo=`date -d "${data_modelo:0:8}  ${data_modelo:8:2}:00 6 hours " +"%Y%m%d%H"`
data_prazo=`date -d "${data_modelo:0:8} 18:00 1 day " +"%Y%m%d%H"`

k=1

while [ ${data_previsao} -ge ${data_prazo} ]; do
	echo $data_previsao
    arquivo_prec_gfs="GFS.PREV.PREC.${data_modelo}.${data_previsao}.nc"

    # Nome dos arquivos do GFS.
	arquivo_temp_ur="GFS.PREV.TEMP2m.RH2m.${data_modelo}.${data_previsao}.nc"

    # As previsões do GFS para até 10 dias são a cada 6 horas, e do dia 11 até o dia 17, são a cada 12 horas.
	# A ideia foi copiar o arquivo das 12UTC para 18UTC para não alterar a estrutura do script.
    if [ $k == 1 ] 
	then 
	   cp ${dirin_gfs}/GFS.PREV.PREC.${data_modelo}.`date -d "${data_modelo:0:8} 12:00 14 day " +"%Y%m%d%H"`.nc ${dirin_gfs}/${arquivo_prec_gfs} 
  	   cp ${dirin_gfs}/GFS.PREV.TEMP2m.RH2m.${data_modelo}.`date -d "${data_modelo:0:8} 12:00 14 day " +"%Y%m%d%H"`.nc ${dirin_gfs}/${arquivo_temp_ur} 
	fi
    
	cp ${tmp}/arquivo.prev.prec.tmp ${tmp}/arquivo.prev.prec.${data_previsao}

	echo ${dirin_gfs}/${arquivo_prec_gfs} >> ${tmp}/arquivo.prev.prec.${data_previsao}
	
	# Nome dos arquivos do GFS.
	#arquivo_temp_ur="GFS.PREV.TEMP2m.RH2m.${data_modelo}.${data_previsao}.nc"

	let k=$k+1
	
	# Lista com os nomes dos 120 arquivos de precipitação.
	nome_arquivos=$(cat ${tmp}/arquivo.prev.prec.${data_previsao} | xargs)

	# Número de arquivos (dias) que serão lidos => 120 no total.
	nd=$(echo ${nome_arquivos} | wc -w) 

	nt=$(($nd-1)) # Usado no loop da precipitação acumulada => 120 - 1 = 119

	# Criação do script em NCL para gerar o risco de fogo previsto.

cat << EOF > ${tmp}/rf.prev.${data_previsao}.ncl

;load "/usr/local/ncarg/lib/ncarg/nclscripts/csm/gsn_code.ncl"
;load "/usr/local/ncarg/lib/ncarg/nclscripts/csm/gsn_csm.ncl"
;load "/usr/local/ncarg/lib/ncarg/nclscripts/csm/contributed.ncl"
;load "/usr/local/ncarg/lib/ncarg/nclscripts/csm/shea_util.ncl"

; Dados de entrada (diário) necessários para o cálculo do risco de 
; fogo (RF):
; 1 - Precipitação (mm/dia);
; 2 - Temperatura do Ar (°C);
; 3 - Umidade Relativa do Ar (décimos).

begin

print("")
print("Abrindo o arquivo de temperatura e umidade relativa.")
print("")

f = addfile("${dirin_gfs}/${arquivo_temp_ur}","r") ; Abertura do arquivo de previsão do GFS.

t2m  = f->TEMP2m(0,:,:)  ; Importação da variável temperatura a 2m (K).

t2m  = t2m - 273.15      ; Converte a Temperatura de Kelvin para Celsius.

ur2m = f->RH2m(0,:,:)    ; Importação da variável umidade relativa a 2m (%).

ur2m = ur2m/100.         ; Umidade Relativa em décimos.

print("")
print("Abrindo os arquivos de precipitação.")
print("")

; Leitura dos arquivos de precipitação. 

lista_arquivos = systemfunc("ls ${nome_arquivos}")

g = addfiles(lista_arquivos,"r")

ListSetType(g,"cat")

nome_var_precip = "prec" ; Nome da variável do arquivo de precipitação do imerg.

; A dimensão tempo (time) foi invertida (::-1). Isso foi feito para facilitar 
; o trabalho com as datas dos arquivos.
; Como a dimensão tempo foi invertida, irá aparecer a seguinte mensagem:
; warning:error attempting to fix non-monotonic aggregation variable
; Pode continuar o cálculo sem problemas.

precip = g[:]->\$nome_var_precip\$(::-1,:,:)  ; Importação da variável precipitação.

print("")
print("Abrindo o arquivo de mapa de vegetação.")
print("")

; Diretório e nome do arquivo onde se encontra o mapa de vegetação.

dir_mapa_veg     = "/home/queimadas/INPE_FireRiskModel/data/input/Veg_Map_2020/"
arquivo_mapa_veg = "Merge_MapBiomas_V5_IGBP_C6_${ano_mapa_veg}.nc"

h = addfile(dir_mapa_veg+arquivo_mapa_veg,"r") ; Abertura do arquivo de vegetação.

mapa_veg = h->Band1(:,:) ; Importação da variável do mapa de vegetação.
    	                    ; Essa variável deve ser "integer" e não "short" ou "float" se não dará erro. 
	            		    ; short Band1(lat, lon) ; => Visto digitando => ncdump -h IGBP_c6_MAPBIOMA_v3_2017_001_RF_ok.nc
        	                ; A conversão é feita no cálculo do risco básico por meio da função:
        	                ; floattoint(mapa_veg(i,k).
			                ; O arquivo de vegetação deve ser orientado de sul para norte. Como o mapa está de norte para sul, 
			                ; foi feita a inversão na sua orientação, por isso o "::-1".

mapa_veg@_FillValue = 0.0   ; Torna a classe zero (superfícies líquidas) UNDEF, isto é, não será feito o cálculo do RF nesses pontos de grade.

dim_veg  = dimsizes(mapa_veg) ; Informações sobre o arquivo de vegetação.
nlat_veg = dim_veg(0)         ; Número de pontos de latitude.
nlon_veg = dim_veg(1)         ; Número de pontos de longitude.

; Domínio do mapa de vegetação.
latS = mapa_veg&lat(0)
latN = mapa_veg&lat(nlat_veg-1)
lonW = mapa_veg&lon(0)
lonE = mapa_veg&lon(nlon_veg-1)

dim  = dimsizes(precip) ; Retorna as dimensões da variável dim.

nlat_prec = dim(1) ; nlat_prec = número de pontos de latitude.
nlon_prec = dim(2) ; nlon_prec = número de pontos de longitude.

vprec = new((/${nd},nlat_prec,nlon_prec/),float) ; Cria uma variável vazia com 120 tempos e 
                                                 ; com as mesmas dimensões lat/lon do arquivo de 
                                                 ; precipitação para calcular a precipitação acumulada. 

print("")
print("Calculando a precipitação acumulada")
print("")

; Cálculo da precipitação acumulada (os dias são olhados para trás).

vprec(0,:,:) = precip(0,:,:) ; Valor de "prec1". Foi feito separadamente 
                             ; porque não há o tempo anterior.

i = 1 ; Inicia o contador.

do while(i.le.${nt}) ; Os demais "prec": prec2, prec3, prec4, prec5, prec10, prec15,
                     ; prec30, prec60, prec90 e prec120.
                     ; Exemplo: prec2 = prec(t=2)+prec(t=1)
                     ; Exemplo: prec10 = prec(t=1)+prec(t=2)+...+prec(t=10)

   vprec(i,:,:) = vprec(i-1,:,:) + precip(i,:,:)

i = i + 1
end do

print("")
print("Calculando o fator de precipitação (fp)")
print("")

; Valores das constantes da função exponencial utilizadas para calcular o fator 
; de precipitação (fp).

cte = (/-0.14,-0.07,-0.04,-0.03,-0.02,-0.01,-0.008,-0.004,-0.002,-0.001,-0.0007/)

fp = new((/11,nlat_prec,nlon_prec/),float) ; Cria uma nova variável para armazenar os 
                                           ; valores de fp com as mesmas dimensões 
                                           ; lat/lon do arquivo de precipitação.

fp(0,:,:) = exp(cte(0)*vprec(0,:,:)) ; Valor do primeiro fp1. Foi feito 
                                     ; separadamente porque não há o tempo 
                                     ; anterior.

j = 1

do while(j.le.4) ; Demais fp: fp2, fp3, fp4 e fp5.

   fp(j,:,:) = exp(cte(j)*(vprec(j,:,:)-vprec(j-1,:,:))) ; Cálculo do fp.

j = j + 1
end do

fp(5,:,:)  = exp(cte(5)  * (vprec(9,:,:)   - vprec(4,:,:)))   ; Valor do fp6a10.
fp(6,:,:)  = exp(cte(6)  * (vprec(14,:,:)  - vprec(9,:,:)))   ; Valor do fp11a15.
fp(7,:,:)  = exp(cte(7)  * (vprec(29,:,:)  - vprec(14,:,:)))  ; Valor do fp16a30.
fp(8,:,:)  = exp(cte(8)  * (vprec(59,:,:)  - vprec(29,:,:)))  ; Valor do fp31a60.
fp(9,:,:)  = exp(cte(9)  * (vprec(89,:,:)  - vprec(59,:,:)))  ; Valor do fp61a90.
fp(10,:,:) = exp(cte(10) * (vprec(119,:,:) - vprec(89,:,:)))  ; Valor do fp91a120.

copy_VarCoords(precip(:10,:,:),fp) ; Copia as coordenadas latitutde/longitude de precip para fp.

print("")
print("Calculando o fator PSE")
print("")

pse = new((/1,nlat_prec,nlon_prec/),float) ; Cria uma nova variável para armazenar os valores de pse.

; Cálculo dos dias de secura (pse).

pse(0,:,:) = 105*fp(0,:,:)*fp(1,:,:)*fp(2,:,:)*fp(3,:,:)*fp(4,:,:)*fp(5,:,:)*fp(6,:,:)*fp(7,:,:)*fp(8,:,:)*fp(9,:,:)*fp(10,:,:)

copy_VarCoords(precip(0,:,:),pse(0,:,:))

; Valores da constante "A" para cada tipo de vegetação. São 17 valores para cada classe.

;A = (/-999.9,2,1.5,2,1.72,2,2.4,3,2.4,3,6,1.5,4,-999.9,4,-999.9,-999.9/)

A = (/-999.9,6,4,3,2.4,2,1.72,1.5/)

A@_FillValue = -999.9 ; Definindo o valor ausente (_FillValue ou missing_value) ou NODATA.

; Valores de pse máximo para cada classe de vegetação. São 17 valores, um para cada classe.

;pse_max = (/-999.9,90.,120.,90.,105.,90.,75.,60.,75.,60.,30.,120.,45.,-999.9,45.,-999.9,-999.9/)

pse_max = (/-999.9,30,45,60,75,90,105,120/)

pse_max@_FillValue = -999.9 ; Definindo o valor ausente (_FillValue ou missing_value) ou NODATA.

; Interpolação do PSE de 10km (dado original de precipitação do IMERG) para 1km utilizando as informações das coordendadas do mapa de vegetação.

; Informações obtidas do mapa de vegetação de 1km.
newlat       = fspan(latS,latN,nlat_veg)
newlon       = fspan(lonW,lonE,nlon_veg)
newlat@units = "degrees_north"
newlon@units = "degrees_east"
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

pse_int_1km = linint2_Wrap(pse&lon,pse&lat,pse,True,newlon,newlat,0) ; Função que realiza a interpolação.

; Cria o nome das dimensões/coordenadas e valores associados.
pse_int_1km!0   = "time"
pse_int_1km!1   = "lat"
pse_int_1km!2   = "lon"
pse_int_1km&lat = newlat
pse_int_1km&lon = newlon

; Fim da interpolação do PSE para 1km;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

print("")		
print("Calculando o risco básico de fogo (rb)")
print("")

rb = new((/1,dimsizes(pse_int_1km&lat),dimsizes(pse_int_1km&lon)/),float) ; Cria uma nova variável para armazenar os 
                                                                          ; valores de rb.
copy_VarCoords(pse_int_1km,rb)

do i = 0,nlat_veg-1

   do k = 0,nlon_veg-1

        ; Se pse > pse_max.

        if((.not.ismissing(pse_int_1km(0,i,k))).and.(.not.ismissing(pse_max(floattoint(mapa_veg(i,k))))) \  
            .and.any((pse_int_1km(0,i,k)).gt.(pse_max(floattoint(mapa_veg(i,k)))))) then
            rb(0,i,k) = 0.8 ; Valor de rb será igual a 0.8.

        ; Caso contrário, calcula o rb de acordo com a equação abaixo.

        else 

            rb(0,i,k) = (0.8*(1+sin((A(floattoint(mapa_veg(i,k)))*pse_int_1km(0,i,k)-90)*(3.1416/180))))/2.0

        end if

   end do

end do

print("")
print("Calculando o fator FU")
print("")

FU = (-0.008*ur2m)+1.3 ; Fator de Umidade (FU). Alterado em 11/04/2019 de "-0.006" para "-0.008". O objetivo consiste em incluir a sazonalidade do RF.

copy_VarCoords(ur2m,FU)

; Interpolação do fator FU de 18km (dado original do BAM) para 1km.

FU_int_1km = linint2_Wrap(FU&lon,FU&lat,FU,True,newlon,newlat,0) ; Função que realiza a interpolação.

; Cria o nome das dimensões e valores das coordenadas.
FU_int_1km!0   = "lat"
FU_int_1km!1   = "lon"
FU_int_1km&lat = newlat
FU_int_1km&lon = newlon

; Fim da interpolação do fator FU para 1km;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

print("")
print("Calculando o fator FT")
print("")

FT = (0.02*t2m)+0.4   ; Fator de Temperatura (FT).

copy_VarCoords(t2m,FT)

; Interpolação do fator FT de 25km (dado original do GFS) para 1km.

FT_int_1km = linint2_Wrap(FT&lon,FT&lat,FT,True,newlon,newlat,0) ; Função que realiza a interpolação.

; Cria o nome das dimensões e valores das coordenadas.
FT_int_1km!0   = "lat"
FT_int_1km!1   = "lon"
FT_int_1km&lat = newlat
FT_int_1km&lon = newlon

; Fim da interpolação do fator FU para 1km;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

print("")
print("Calculando o risco de fogo final (rbf)")
print("")

; Reduzindo a dimensão de "rb" para duas dimensões, isto é, apenas latitude e 
; longitude para que sejam iguais a FT e FU.

rbf = rb(0,:,:)*FT_int_1km*FU_int_1km  ; Cálculo do risco de fogo final (rbf).

rbf = where(rbf.gt.1,1,rbf) ; Quando rbf for maior que 1, recebe o valor máximo 
                            ; que é igual a 1, e no caso contrário, recebe o valor de rbf.

copy_VarCoords(FT_int_1km,rbf) ; Copia as coordenadas de latitutde e longitude da variável FT_int_1km para rbf.

; GM-110419
; Correção do risco de fogo pela latitude, ou Fator Latitude (FL). Utiliza-se o valor absoluto da latitude, por isso, o uso do função "abs()".
; Equação desenvolvida pelo Setzer em 05/04/2019.

print("")
print("Calculando o fator de latitude")
print("")

FLAT = (1 + abs(rbf&lat) * 0.003) ; Fator latitudinal.

aux = rbf(:,0) ; Artíficio para copiar os valores da coordenada de latitude para FLAT.

copy_VarCoords(aux,FLAT)

FLAT_C = conform_dims(dimsizes(rbf), FLAT, 0) ; A variável FLAT é 1D, só tem latitude, e ela 
					      ; foi convertida para 2D.

copy_VarCoords(rbf,FLAT_C)

print("")
print("Abrindo o arquivo de topografia")
print("")

; GM-110419
; Correção do risco de fogo pela topografia (metros), ou Fator Topográfico (FTOP):
; Equação desenvolvida pelo Setzer em 05/04/2019.
; Abertura do arquivo de topografia. O arquivo foi gerado pelo Alessandro a partir do GTOPO30.
; O arquivo de topografia tem que ter o numero de pontos do arquivo do mapa de vegetaçao.
m = addfile("/home/queimadas/INPE_FireRiskModel/data/input/topografia/GeoTOPOAmericaSulCentral_V3.nc","r") ; GM: 03/03/2021-> Interpolei o mapa de topografia para a mesma resolucao do mapa de vegetacao.

elev = m->Band1

print("")
print("Calculando o fator de elevação")
print("")

FTOP = 1 + elev * 0.00003 ; Fator de elevação

copy_VarCoords(rbf,FTOP)

rbfn = rbf * FLAT_C * FTOP ; Multiplicação do RF pelos fatores de latitude e elevação, respectivamente.

copy_VarCoords(rbf,rbfn)

rbfn = where(rbfn.gt.1,1,rbfn) ; Quando rbfn for maior que 1, recebe o valor máximo 
                               ; que é igual a 1, e no caso contrário, recebe o valor de rbf.


xT  = decimalPlaces(rbfn,2,True)

;;;;;;;;;;; Criação do arquivo netCDF ;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

print("")
print("Gerando o arquivo NetCDF para o dia " + ${data_previsao})
print("")

dir_out_netcdf = "${dir_output_netcdf}" ; Diretório onde ficarão as saídas dos arquivos 
			      ; netCDF de Risco de Fogo.

; Remove qualquer arquivo existente.
system("/bin/rm -f "+dir_out_netcdf+"/RF.PREV."+${data_previsao}+".nc") 

; Nome do arquivo netCDF a ser criado.
ncdf = addfile(dir_out_netcdf+"/RF.PREV."+${data_previsao}+".nc","c")   

; Criação de atributos globais. Fornece informações sobre o arquivo 
; netCDF que será criado.

fAtt               = True
fAtt@title         = "Risco de fogo previsto para o dia " + ${data_previsao}
fAtt@Conventions   = "None"
fAtt@codigo        = "Guilherme Martins - guilherme.martins@inpe.br"
fAtt@author        = "Alberto Setzer - alberto.setzer@inpe.br"
fAtt@link          = "http://www.inpe.br/queimadas/"
fAtt@source        = "Codigo feito no software NCL " + get_ncl_version()
fAtt@creation_date = systemfunc ("date")

fileattdef(ncdf,fAtt )
filedimdef(ncdf,"time",-1,True) 

;ncdf->rbf = rbf
ncdf->rbf = xT

;;;;;;;;;;; Fim da criação do arquivo netCDF ;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

end

EOF

	echo "/home/queimadas/miniconda3/envs/ncl_stable/bin/ncl -npQ ${tmp}/rf.prev.${data_previsao}.ncl 2>> ${dir_log}/log.${data_modelo}.${data_previsao}" >> ${tmp}/paralelizar_RF_PREV.txt

	#remove lista de arquivos utilizados em cada simulação
	rm ${tmp}/arquivo.prev.prec.${data_previsao}

	# Incremento do loop.
	#data_previsao=`date -d "${data_previsao:0:8}  ${data_previsao:8:2}:00 24 hours ago" +"%Y%m%d%H"`
	data_previsao=`date -d "${data_previsao:0:8}  18:00 7 day ago" +"%Y%m%d%H"`
done

#remove lista de arquivos utilizados em cada simulação
rm -f ${tmp}/arquivo.prev.prec.tmp

# Executa todos os programas de forma paralela.
/usr/bin/parallel -j 2 -- < ${tmp}/paralelizar_RF_PREV.txt

rm -f ${tmp}/paralelizar_RF_PREV.txt

arquivos=$(ls ${dir_output_netcdf}/RF.PREV.* | wc -l)
cont=0

# O 2 significa que são gerados 2 arquivos de previsão.
while [ ${arquivos} -ne 2 ]; do
	arquivos=$(ls ${dir_output_netcdf}/RF.PREV.* | wc -l)
		
	sleep 600

	let cont=$cont+1;
	
	if [ $cont -eq 1 ]; then
		echo " PROBLEMA - FALTAM ARQUIVOS EM ${dir_output_netcdf}"
	
     	exit 1
	fi
done

Dia=2

data_previsao=`date +"%Y%m%d" -d "${data_final} 14 days "`"18"

while [ ${data_previsao} -ge ${data_prazo} ]
do

	echo $data_previsao

	arquivo_RF_PREV="RF.PREV.${data_previsao}.nc"

	# Utilizado para consertar a data do arquivo NetCDF.
	hhc=${data_previsao:8:2}
	diac=${data_previsao:6:2}
	mesc=${data_previsao:4:2}
	anoc=${data_previsao:0:4}

	# Consertando a data do arquivo.
	${DIR_BIN}/cdo -s -r -setmissval,-999 -settaxis,${anoc}-${mesc}-${diac},${hhc}:00:00,6hour ${dir_output_netcdf}/${arquivo_RF_PREV} ${dir_output_netcdf}/tmp.RF.PREV.${data_previsao}.nc
	mv ${dir_output_netcdf}/tmp.RF.PREV.${data_previsao}.nc ${dir_output_netcdf}/${arquivo_RF_PREV}

	# Gera o arquivo TIF a partir do NetCDF.
	${DIR_BIN}/gdal_translate -of GTiff -a_srs EPSG:4326 -co TILED=YES -co COPY_SRC_OVERVIEWS=YES -co COMPRESS=LZW ${dir_output_netcdf}/${arquivo_RF_PREV} ${dir_output_tif}/RF.PREV.${data_previsao}.tif

	if [ $hhc -eq "18" ] ; then

		ln -sf ${dir_output_tif}/RF.PREV.${data_previsao}.tif /home/queimadas/INPE_FireRiskModel/dados/mapfiles/tmp/RF.PREV.D${Dia}.tif
                cp ${dir_output_tif}/RF.PREV.${data_previsao}.tif ${dir_output_tif}/RF.PREV.T$((${Dia}-1)).${data_previsao}.tif  # A pedido do Jonatas - GM: 10/03/2021.

		echo "${data_previsao} --- ${Dia}"
	
		let Dia=$Dia-1
	fi

	rm ${tmp}/rf.prev.${data_previsao}.ncl

	#incremento loop
	#data_previsao=`date -d "${data_previsao:0:8}  ${data_previsao:8:2}:00 6 hours ago" +"%Y%m%d%H"`
	data_previsao=`date -d "${data_previsao:0:8}  18:00 7 day ago" +"%Y%m%d%H"`
done

rm -f ${tmp}/paralelizar_RF_PREV.txt
rm -f ${tmp}/RF.PREV.*.tif

cp ${dir_output_tif}/RF.PREV.T0.????????18.tif ${dir_output_tif}/RF.PREV.T7.tif
cp ${dir_output_tif}/RF.PREV.T1.????????18.tif ${dir_output_tif}/RF.PREV.T14.tif

rm ${dir_output_tif}/RF.PREV.2*.tif

# enviando via lftp arquivos para area geroserver terrabrasilis
lftp -u 'helder,HelQuEim@da5' sftp://150.163.2.29 -e "cd /dados/vms/cluster/geoserver/cluster/gs_datadir/data_file; put "${dir_output_tif}/RF.PREV.T7.tif" ; quit"
lftp -u 'helder,HelQuEim@da5' sftp://150.163.2.29 -e "cd /dados/vms/cluster/geoserver/cluster/gs_datadir/data_file; put "${dir_output_tif}/RF.PREV.T14.tif" ; quit"

# enviando via scp arquivos para area dados do volume cianorte / geoserver dados.inpe
scp ${dir_output_tif}/RF.PREV.T7.tif pedro.lagden@150.163.212.54:/prod_qmd2/INPE_FireRiskModel/data/output/2.2/RF_PREV/tif/
scp ${dir_output_tif}/RF.PREV.T14.tif pedro.lagden@150.163.212.54:/prod_qmd2/INPE_FireRiskModel/data/output/2.2/RF_PREV/tif/

datafinal=`date +%s`
soma=`expr $datafinal - $datainicial`
resultado=`expr 10800 + $soma`
tempo=`date -d @$resultado +%H:%M:%S`
echo " Tempo gasto: $tempo "

exit 0
