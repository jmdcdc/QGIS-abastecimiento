# ==============================================================================
# SCRIPT DE PYQGIS: ANÁLISIS DE DENSIDAD DE COBERTURA EN PARCELAS URBANAS
# ==============================================================================
# Desarrollado para compatibilidad estricta con QGIS 3.44.10.
# Soluciona la importación de tipos mediante el uso de QVariant de PyQt5.

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterVectorDestination,
    QgsProcessing,
    QgsField,
    QgsFeature,
    QgsFeatureSink,
    QgsApplication
)
# IMPORTACIÓN CRÍTICA: En QGIS 3, QgsVariant no existe en qgis.core.
# Se debe utilizar QVariant importado desde la librería nativa de Qt (PyQt5).
from PyQt5.QtCore import QVariant
import processing

# Definimos la clase que heredará de QgsProcessingAlgorithm para integrarse en la caja de herramientas
class CoberturaHidrantesParcelasAlg(QgsProcessingAlgorithm):
    
    # --------------------------------------------------------------------------
    # CONSTANTES DE ENTRADA Y SALIDA
    # --------------------------------------------------------------------------
    # Definimos cadenas fijas de texto para no escribir nombres de variables a mano.
    # Esto evita errores de escritura (typos) en el cuerpo del código.
    PARCELAS = 'PARCELAS'
    BOCAS_INCENDIOS = 'BOCAS_INCENDIOS'
    OUTPUT = 'OUTPUT'

    # --------------------------------------------------------------------------
    # CONFIGURACIÓN DE LA INTERFAZ DE USUARIO (INPUTS)
    # --------------------------------------------------------------------------
    def initAlgorithm(self, config=None):
        # Parámetro 1: Capa de entrada para las parcelas urbanas.
        # Restringimos el tipo de geometría únicamente a polígonos ([QgsProcessing.TypeVectorPolygon]).
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.PARCELAS, 
                'Tema de parcelas (Polígonos)', 
                [QgsProcessing.TypeVectorPolygon]
            )
        )
        
        # Parámetro 2: Capa de entrada para los puntos de agua / hidrantes.
        # Restringimos el tipo de geometría únicamente a puntos ([QgsProcessing.TypeVectorPoint]).
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.BOCAS_INCENDIOS, 
                'Tema de bocas de incendios (Puntos)', 
                [QgsProcessing.TypeVectorPoint]
            )
        )
        
        # Parámetro 3: Destino donde el usuario guardará la capa final generada.
        # Puede ser un archivo físico (Shapefile, GeoPackage) o una capa temporal en memoria.
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT, 
                'Resultado de la densidad de cobertura'
            )
        )

    # --------------------------------------------------------------------------
    # METADATOS DEL ALGORITMO
    # --------------------------------------------------------------------------
    def name(self): 
        # Nombre técnico/interno del script para QGIS (Debe ser único, sin espacios ni mayúsculas).
        return 'hidrantes_coberturaparcelas'
        
    def displayName(self): 
        # Nombre comercial o etiqueta amigable que el usuario leerá en la interfaz gráfica.
        return 'Hidrantes - Calcular cobertura bocas de incendio en parcelas'
        
    def group(self): 
        # Nombre visual del grupo o carpeta contenedora dentro de la caja de herramientas.
        return 'Aquavall - Abastecimiento'
        
    def groupId(self): 
        # ID interno del grupo contenedor (Modificado según tu solicitud a 'abastecimiento').
        return 'aquavall_abastecimiento'
        
    def createInstance(self): 
        # Instancia la clase para que QGIS pueda duplicar el proceso si corre hilos en paralelo.
        return CoberturaHidrantesParcelasAlg()

    # --------------------------------------------------------------------------
    # NÚCLEO DE PROCESAMIENTO (PROCESSTALGORITHM)
    # --------------------------------------------------------------------------
    def processAlgorithm(self, parameters, context, feedback):
        # Traducimos los parámetros de la interfaz a fuentes de objetos vectoriales legibles.
        source_parcelas = self.parameterAsSource(parameters, self.PARCELAS, context)
        source_bocas = self.parameterAsSource(parameters, self.BOCAS_INCENDIOS, context)

        # ......................................................................
        # PASO A: EJECUCIÓN DEL BUFFER (ÁREAS DE INFLUENCIA DE 180 METROS)
        # ......................................................................
        # Mandamos un mensaje informativo a la pestaña de "Log" del proceso.
        feedback.pushInfo('Creando áreas de influencia de 180 metros...')
        
        # Definimos el diccionario de parámetros exactos requeridos por 'native:buffer'.
        params_buffer = {
            'INPUT': parameters[self.BOCAS_INCENDIOS], # Capa original de puntos sacada de la interfaz.
            'DISTANCE': 180.0,                         # Radio de cobertura solicitado (180 metros).
            'SEGMENTS': 8,                             # Nivel de aproximación de la curva (8 segmentos por cuadrante).
            'END_CAP_STYLE': 0,                        # 0 equivale a estilo final Redondo.
            'JOIN_STYLE': 0,                           # 0 equivale a uniones de líneas Redondas.
            'MITER_LIMIT': 2.0,                        # Límite de inglete estándar.
            'DISSOLVE': False,                         # Falso para mantener los círculos de forma individual.
            'OUTPUT': 'memory:buffer_bocas'            # Guardado rápido en la memoria RAM (Evita crear archivos basura).
        }
        # Ejecutamos el algoritmo nativo del núcleo de QGIS.
        res_buffer = processing.run('native:buffer', params_buffer, context=context, feedback=feedback)
        # Extraemos el objeto capa resultante de la memoria RAM.
        layer_buffers = res_buffer['OUTPUT']

        # ......................................................................
        # PASO B: REPARACIÓN DE GEOMETRÍAS DE LAS PARCELAS
        # ......................................................................
        feedback.pushInfo('Reparando geometrías de las parcelas...')
        
        # Configuramos los parámetros para limpiar geometrías inválidas (auto-intersecciones, bucles).
        params_fix = {
            'INPUT': parameters[self.PARCELAS],        # Capa original de parcelas seleccionada por el usuario.
            'OUTPUT': 'memory:parcelas_fijas'          # Resultado almacenado en memoria RAM temporal.
        }
        # Ejecutamos el algoritmo de limpieza nativo de QGIS.
        res_fix = processing.run('native:fixgeometries', params_fix, context=context, feedback=feedback)
        layer_parcelas_fijas = res_fix['OUTPUT']

        # ......................................................................
        # PASO C: PREPARACIÓN DE LA ESTRUCTURA DE LA NUEVA CAPA DE SALIDA
        # ......................................................................
        # Clonamos la lista de campos (atributos) existentes de las parcelas ya reparadas.
        fields = layer_parcelas_fijas.fields()
        
        # Añadimos nuestro nuevo campo numérico llamado "cobertura" a la lista.
        # QVariant.Int define que el campo alojará números enteros sin decimales. Le asignamos longitud 10.
        fields.append(QgsField('cobertura', QVariant.Int, len=10))

        # El sumidero (sink) se encarga de ir escribiendo físicamente el archivo final en el disco duro.
        # Le pasamos la nueva estructura de campos, el tipo geométrico y el sistema de coordenadas de origen (CRS).
        (sink, dest_id) = self.parameterAsSink(
            parameters, 
            self.OUTPUT, 
            context, 
            fields, 
            layer_parcelas_fijas.wkbType(), 
            layer_parcelas_fijas.sourceCrs()
        )

        # ......................................................................
        # PASO D: OPTIMIZACIÓN Y EXTRACCIÓN DE ELEMENTOS EN MEMORIA
        # ......................................................................
        # Convertimos el iterador de círculos en una lista fija de Python.
        # Esto nos permite leer las geometrías directamente de la RAM miles de veces sin re-leer el archivo.
        lista_buffers = [feat for feat in layer_buffers.getFeatures()]
        
        # Contamos cuántas parcelas hay en total para calcular los porcentajes del progreso de carga.
        total_parcelas = layer_parcelas_fijas.featureCount()
        
        feedback.pushInfo('Calculando intersecciones por parcela...')
        
        # ......................................................................
        # PASO E: BUCLE PRINCIPAL DE INTERSECCIÓN ESPACIAL (POLÍGONO VS CÍRCULOS)
        # ......................................................................
        # Recorremos cada parcela usando 'enumerate' para saber en qué fila numérica estamos (index).
        for index, feat_parcela in enumerate(layer_parcelas_fijas.getFeatures()):
            # Si el usuario pulsa el botón "Cancelar" en la ventana de QGIS, rompemos el bucle inmediatamente.
            if feedback.isCanceled():
                break

            # Extraemos la geometría espacial de la parcela actual.
            geom_parcela = feat_parcela.geometry()
            # Inicializamos nuestro contador a cero para esta parcela en particular.
            contador_intersecciones = 0

            # Validamos que la geometría no sea nula ni se encuentre vacía en el mapa.
            if geom_parcela and not geom_parcela.isEmpty():
                # Evaluamos de forma indexada contra cada círculo de 180m disponible en la lista.
                for feat_buffer in lista_buffers:
                    # El operador lógico matemático .intersects evalúa si hay un solape geométrico real.
                    if geom_parcela.intersects(feat_buffer.geometry()):
                        # Si hay contacto o cruce, incrementamos el valor del contador numérico en +1.
                        contador_intersecciones += 1

            # Creamos una entidad vacía clonando los datos estructurales de la parcela original evaluada.
            nueva_feat = QgsFeature(feat_parcela)
            # Extraemos la fila de valores alfanuméricos de sus atributos.
            nuevos_atributos = feat_parcela.attributes()
            # Añadimos el valor entero final del contador al final de la fila de atributos.
            nuevos_atributos.append(contador_intersecciones)
            # Inyectamos la nueva lista de atributos modificada de vuelta en la entidad.
            nueva_feat.setAttributes(nuevos_atributos)
            
            # Mandamos la entidad lista con su nueva columna rellenada al sumidero de escritura veloz (FastInsert).
            sink.addFeature(nueva_feat, QgsFeatureSink.FastInsert)
            
            # Actualizamos la barra de porcentaje de la interfaz gráfica basándonos en la parcela actual procesada.
            feedback.setProgress(int((index / total_parcelas) * 100))

        # Retornamos el ID final de la capa para que QGIS la pinte de forma automática en el lienzo de mapas.
        return {self.OUTPUT: dest_id}

# ==============================================================================
# DISPARADOR DE REGISTRO DIRECTO EN LA INTERFAZ DE QGIS
# ==============================================================================
# Este bloque detecta la ejecución dentro de la Consola de Python e inyecta la herramienta.
try:
    QgsApplication.processingRegistry().addAlgorithm(CoberturaHidrantesParcelasAlg())
    print("¡Algoritmo registrado de forma exitosa en la Caja de herramientas!")
except Exception as e:
    print(f"Error crítico al intentar registrar el script: {e}")
