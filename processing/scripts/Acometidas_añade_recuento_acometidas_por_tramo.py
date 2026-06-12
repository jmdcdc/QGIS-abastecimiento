from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterVectorDestination,
    QgsProcessingOutputVectorLayer,
    QgsProcessing,
    QgsField,
    QgsSpatialIndex,
    QgsFeatureSink,
    QgsFeature
)
from PyQt5.QtCore import QVariant

class AddLateralCountAlgorithm(QgsProcessingAlgorithm):
    INPUT_LINES = 'INPUT_LINES'
    INPUT_POINTS = 'INPUT_POINTS'
    OUTPUT = 'OUTPUT'

    ############################################################################
    ## BLOQUE 1: CONFIGURACIÓN, METADATOS Y AYUDA DEL ALGORITMO
    ############################################################################

    def initAlgorithm(self, config=None):
        # Definimos los parámetros de entrada requeridos en la interfaz de usuario
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LINES,
                'Tramos de red (Multilinea)',
                [QgsProcessing.TypeVectorLine]
            )
        )
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_POINTS,
                'Acometidas / Conexiones (Puntos)',
                [QgsProcessing.TypeVectorPoint]
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT,
                'Capa de salida con recuento'
            )
        )

    def name(self):
        # Nombre técnico interno del comando
        return 'recuento_acometidas_tramo_tolerancia'

    def displayName(self):
        # Nombre público visible en la caja de herramientas
        return 'Acometidas – Añade recuento acometidas por tramo de red'

    def group(self):
        # Categoría principal en el árbol de procesos
        return 'Aquavall - Abastecimiento'

    def groupId(self):
        # Identificador del grupo para organización interna
        return 'aquavall_abastecimiento'

    def shortHelpString(self):
        # Esta función genera el texto de ayuda formateado en HTML para el panel lateral de QGIS
        return """
        <h2>Descripción del algoritmo</h2>
        <p>Esta herramienta realiza un enlace espacial optimizado entre los tramos de red y las acometidas o conexiones domiciliarias.</p>
        
        <h3>Funcionamiento:</h3>
        <ul>
            <li>Calcula de forma automática cuántas acometidas pertenecen a cada tramo de tubería.</li>
            <li>Aplica un <b>margen de tolerancia de 10 centímetros</b> para absorber errores de digitalización en el EPSG:25830.</li>
            <li>Crea índices espaciales en memoria para procesar grandes volúmenes de datos en pocos segundos.</li>
        </ul>

        <h3>Resultado:</h3>
        <p>Se genera una nueva capa lineal idéntica a la de entrada, pero incluyendo el nuevo campo numérico <b>num_acometidas</b> en su tabla de atributos con el conteo final.</p>
        """

    def createInstance(self):
        return AddLateralCountAlgorithm()

    ############################################################################
    ## BLOQUE 2: PROCESAMIENTO PRINCIPAL DE DATOS
    ############################################################################

    def processAlgorithm(self, parameters, context, feedback):
        # Convertimos los parámetros de la interfaz en objetos de acceso a datos (sources)
        source_lines = self.parameterAsSource(parameters, self.INPUT_LINES, context)
        source_points = self.parameterAsSource(parameters, self.INPUT_POINTS, context)

        # Definimos la tolerancia en metros (0.10m = 10cm para EPSG:25830)
        TOLERANCIA_METROS = 0.10

        # Copiamos la estructura de la tabla original del tema de tramos de red
        fields = source_lines.fields()
        field_name = 'num_acometidas'
        
        # Evaluamos si el campo ya existe para evitar errores por duplicidad
        if fields.indexFromName(field_name) == -1:
            fields.append(QgsField(field_name, QVariant.Int))

        # Inicializamos el sumidero (Sink) donde se escribirá físicamente el nuevo tema resultado
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            source_lines.wkbType(),
            source_lines.sourceCrs()
        )

        ############################################################################
        ## BLOQUE 3: OPTIMIZACIÓN ESPACIAL (ÍNDICES Y MEMORIA)
        ############################################################################

        feedback.pushInfo("Construyendo índice espacial para optimizar las acometidas...")
        # El índice espacial almacena las coordenadas de las cajas envolventes de los puntos
        spatial_index_points = QgsSpatialIndex(
            source_points.getFeatures(),
            feedback
        )

        feedback.pushInfo("Cargando geometrías de acometidas en memoria rápida...")
        # Guardamos las geometrías indexadas en un diccionario para evitar lecturas de disco lentas
        points_dict = {}
        for point_feat in source_points.getFeatures():
            points_dict[point_feat.id()] = point_feat.geometry()

        # Configuración del control y cálculo del porcentaje de progreso de la barra visual
        total = source_lines.featureCount()
        step = 100.0 / total if total > 0 else 1

        ############################################################################
        ## BLOQUE 4: CRUCE ESPACIAL CON TOLERANCIA Y RECUENTO
        ############################################################################

        feedback.pushInfo("Calculando enlaces espaciales con zona de influencia de 10cm...")
        
        # Iteramos secuencialmente por cada uno de los tramos de red disponibles
        for current, line_feat in enumerate(source_lines.getFeatures()):
            # Permitimos al usuario detener el proceso de forma segura desde la interfaz
            if feedback.isCanceled():
                break

            # Extraemos la geometría de la línea original
            line_geom = line_feat.geometry()
            
            # Generamos un área de influencia temporal para absorber imprecisiones de digitalización
            # Al usar EPSG:25830, el valor numérico 0.10 se interpreta directamente como metros
            buffered_geom = line_geom.buffer(TOLERANCIA_METROS, 5)
            
            # Consultamos el índice espacial usando la caja envolvente de la geometría ensanchada
            candidate_ids = spatial_index_points.intersects(buffered_geom.boundingBox())
            
            count = 0
            # Evaluamos de forma matemática estricta los puntos candidatos prefiltrados
            for p_id in candidate_ids:
                p_geom = points_dict.get(p_id)
                # Verificamos si el punto realmente intersecta con la zona de influencia de 10cm
                if p_geom and buffered_geom.intersects(p_geom):
                    count += 1

            # Inicializamos una nueva entidad con la estructura de campos actualizada
            new_feat = QgsFeature(fields)
            # Conservamos la geometría de línea original (sin el buffer de 10cm) para el tema de salida
            new_feat.setGeometry(line_geom)
            
            # Traspasamos todos los valores originales de los atributos del tramo
            for attr_idx, value in enumerate(line_feat.attributes()):
                new_feat.setAttribute(attr_idx, value)
                
            # Grabamos el conteo final de acometidas interceptadas en el nuevo campo numérico
            new_feat.setAttribute(field_name, count)
            
            # Inyectamos la entidad procesada en el sumidero de salida de forma rápida
            sink.addFeature(new_feat, QgsFeatureSink.FastInsert)

            # Refrescamos la barra de estado de QGIS
            feedback.setProgress(int(current * step))

        # Retornamos el identificador del nuevo tema generado con los recuentos finalizados
        return {self.OUTPUT: dest_id}

