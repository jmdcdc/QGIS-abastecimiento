# Se importan los componentes necesarios de la API de PyQGIS
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsProcessing,
    QgsFeatureSink,  # Permite usar la bandera de inserción rápida FastInsert
    QgsSpatialIndex  # Estructura de datos para optimizar búsquedas geométricas
)

################################################################################
### BLOQUE 1: DEFINICIÓN DE LA CLASE Y PARÁMETROS DE ENTRADA/SALIDA          ###
################################################################################

class ComprobacionExistenciaDesague(QgsProcessingAlgorithm):
    # Constantes de texto para evitar errores de escritura al llamar parámetros
    TRAMOS = 'TRAMOS'
    VALVULAS = 'VALVULAS'
    CAMPO_ID = 'CAMPO_ID'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        """
        Aquí se define la interfaz del algoritmo (Caja de herramientas).
        Se especifican los tipos de datos que el usuario debe ingresar.
        """
        # Entrada 1: Capa vectorial de tramos (restringida a geometrías de línea)
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.TRAMOS,
                'Tema de tramos de red (Multilíneas) con identificadores de poligonos de corte completados',
                [QgsProcessing.TypeVectorLine]
            )
        )
        
        # Entrada 2: Capa vectorial de válvulas (restringida a geometrías de punto)
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.VALVULAS,
                'Tema de válvulas de desagüe o desacargas (Puntos)',
                [QgsProcessing.TypeVectorPoint]
            )
        )
        
        # Entrada 3: Campo de la tabla de atributos de la capa de tramos
        # Corregido: Se utiliza setHelp() para la ayuda del parámetro específico
        param_campo = QgsProcessingParameterField(
            self.CAMPO_ID,
            'Campo identificador de los polígonos de corte',
            parentLayerParameterName=self.TRAMOS
        )
        param_campo.setHelp('Selecciona la columna que identifica el polígono de corte.')
        self.addParameter(param_campo)
        
        # Salida: Destino donde se creará y guardará la capa resultante
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                'Nombre para el nuevo tema resultante'
            )
        )

################################################################################
### BLOQUE 2: PREPARACIÓN DE DATOS Y CARGA EN MEMORIA (OPTIMIZACIÓN)        ###
################################################################################

    def processAlgorithm(self, parameters, context, feedback):
        """
        Contiene el núcleo lógico del algoritmo. Se ejecuta al pulsar 'Ejecutar'.
        """
        # Se transforman los parámetros de la interfaz en objetos legibles por PyQGIS
        tramos_source = self.parameterAsSource(parameters, self.TRAMOS, context)
        valvulas_source = self.parameterAsSource(parameters, self.VALVULAS, context)
        campo_id = self.parameterAsString(parameters, self.CAMPO_ID, context)

        # Se inicializa el sumidero (sink). Copia la estructura exacta de la capa base:
        # campos (fields), tipo de geometría (wkbType) y sistema de coordenadas (sourceCrs)
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            tramos_source.fields(),
            tramos_source.wkbType(),
            tramos_source.sourceCrs()
        )

        # Informar al usuario en la pestaña de 'Registro' (Log)
        feedback.pushInfo("Cargando tramos de red en memoria...")
        
        # Optimizamos el rendimiento creando un Índice Espacial (R-Tree)
        # Esto evita comparar cada válvula contra absolutamente todos los tramos de la red
        idx_tramos = QgsSpatialIndex()
        dict_tramos = {} # Diccionario Python para acceder a los atributos al instante por su ID
        
        for feature in tramos_source.getFeatures():
            idx_tramos.addFeature(feature)      # Guarda la geometría estructurada en el índice espacial
            dict_tramos[feature.id()] = feature # Asocia el ID del objeto con el objeto completo

################################################################################
### BLOQUE 3: ANÁLISIS ESPACIAL Y ENLACE GEOMÉTRICO                         ###
################################################################################

        # Estructura 'set' para almacenar identificadores únicos sin duplicados
        ids_a_eliminar = set()
        total_valvulas = valvulas_source.featureCount()
        
        # Bucle principal: Analizar la posición de cada válvula
        for step, valvula in enumerate(valvulas_source.getFeatures()):
            # Permite al alumno/usuario cancelar el algoritmo de forma segura a mitad del proceso
            if feedback.isCanceled():
                break

            geom_valvula = valvula.geometry()
            
            # PASO 1 (Filtro rápido): El índice devuelve solo los tramos cuya caja de 
            # contorno (BBox) interseca o rodea el punto de la válvula.
            candidatos_ids = idx_tramos.intersects(geom_valvula.boundingBox())
            
            # PASO 2 (Filtro exacto): Evaluamos geométricamente solo los tramos candidatos
            for tramo_id in candidatos_ids:
                tramo_feat = dict_tramos[tramo_id]
                
                # Comprobación de intersección topológica exacta (Punto toca a la Línea)
                if geom_valvula.intersects(tramo_feat.geometry()):
                    val_id = tramo_feat[campo_id] # Extrae el valor del campo identificador elegido
                    ids_a_eliminar.add(val_id)    # Lo añade a la lista de descartes
            
            # Actualiza dinámicamente la barra de progreso de la interfaz de QGIS
            feedback.setProgress(int(step / total_valvulas * 100))

        feedback.pushInfo(f"Identificadores a eliminar encontrados: {len(ids_a_eliminar)}")

################################################################################
### BLOQUE 4: ESCRITURA DE RESULTADOS Y RETORNO                             ###
################################################################################

        tramos_guardados = 0
        # Recorremos el diccionario de tramos original para decidir cuáles conservar
        for feat_id, tramo_feat in dict_tramos.items():
            # Condición fundamental: Si el identificador NO está en la lista de descarte, se guarda
            if tramo_feat[campo_id] not in ids_a_eliminar:
                # FastInsert acelera la creación del archivo omitiendo comprobaciones de indexación en cada línea
                sink.addFeature(tramo_feat, QgsFeatureSink.FastInsert)
                tramos_guardados += 1

        feedback.pushInfo(f"Proceso finalizado. Tramos restantes guardados: {tramos_guardados}")
        
        # Se retorna un diccionario obligatorio con el ID de la capa generada
        return {self.OUTPUT: dest_id}

################################################################################
### BLOQUE 5: AYUDA Y DOCUMENTACIÓN DE LA INTERFAZ                          ###
################################################################################

    def shortHelpString(self):
        """
        Devuelve el texto formateado en HTML que se muestra en el panel 
        derecho de ayuda al abrir la herramienta en QGIS.
        """
        return """
        <h2>Descripción del Proceso</h2>
        <p>Esta herramienta analiza las redes de agua para detectar qué poligonos de corte carecen de desagüe.</p>
        
        <h3>¿Cómo funciona?</h3>
        <ol>
            <li><b>Carga en memoria:</b> Indexa espacialmente los tramos de la red.</li>
            <li><b>Intersección:</b> Cruza las posiciones de las válvulas de desagüe (puntos) con las líneas.</li>
            <li><b>Identificación:</b> Agrupa los identificadores de los poligonos de corte(campo seleccionado) con un desagüe conectado.</li>
            <li><b>Filtro de salida:</b> Exporta solo los tramos de red cuyos identificadores <b>NO</b> tienen valvula de descarga.</li>
        </ol>
        
        <p><i>Nota académica: Este script implementa optimización R-Tree mediante QgsSpatialIndex para reducir la complejidad computacional.</i></p>
        """

    def helpUrl(self):
        """
        Opcional: Permite enlazar a un manual web o repositorio si el usuario 
        hace clic en el enlace de ayuda de QGIS.
        """
        return "qgis.org"

################################################################################
### BLOQUE 6: METADATOS INTERNOS DEL ALGORITMO                              ###
################################################################################

    def name(self):
        # Nombre técnico interno (Usado en scripts de consola o modelos)
        return 'cortes_agua_poligono_corte_sin_desague'

    def displayName(self):
        # Nombre visible para el usuario final en la caja de herramientas
        return 'Cortes agua - Poligonos de corte sin desagüe'

    def group(self):
        # Nombre del subgrupo contenedor
        return 'Aquavall - Abastecimiento'

    def groupId(self):
        # ID único del grupo contenedor
        return 'aquavall_abastecimiento'

    def createInstance(self):
        # Crea una copia fresca de la clase cuando el entorno de QGIS la invoca
        return ComprobacionExistenciaDesague()
