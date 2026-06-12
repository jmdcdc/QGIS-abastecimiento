from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterFeatureSource,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsProcessing,
    QgsFeatureSink,
    QgsField,
    QgsSpatialIndex,
    NULL
)
from PyQt5.QtCore import QVariant

## BLOQUE 1: DEFINICIÓN DE LA CLASE Y METADATOS DEL ALGORITMO
class AsignaIdPoligonoCorte(QgsProcessingAlgorithm):
    
    def name(self) -> str:
        return 'asigna_id_pol_corte_acometidas'

    def displayName(self) -> str:
        return 'Acometidas – Asigna ID polígono de corte en las acometidas'

    def group(self) -> str:
        return 'Aquavall - Abastecimiento'

    def groupId(self) -> str:
        return 'aquavall_abastecimiento'

    def shortHelpString(self) -> str:
        return (
            "Este algoritmo realiza un enlace espacial entre acometidas (puntos) y "
            "tramos de red (líneas) con una tolerancia de 10 cm.\n\n"
            "Copia el ID del polígono de corte del tramo de red y lo asigna al nuevo "
            "campo 'id_pol_corte' de la acometida. Si no encuentra tramo cercano, "
            "el valor quedará como Nulo."
        )

    def createInstance(self):
        return AsignaIdPoligonoCorte()

## BLOQUE 2: CONFIGURACIÓN DE LOS PARÁMETROS DE ENTRADA Y SALIDA
    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                'TRAMOS_RED',
                'Tema de tramos de red (Líneas)',
                [QgsProcessing.TypeVectorLine]
            )
        )
        
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                'ACOMETIDAS',
                'Tema de acometidas (Puntos)',
                [QgsProcessing.TypeVectorPoint]
            )
        )

        self.addParameter(
            QgsProcessingParameterField(
                'CAMPO_ID_ORIGEN',
                'Campo con ID de polígono de corte (en Tramos)',
                parentLayerParameterName='TRAMOS_RED',
                type=QgsProcessingParameterField.Any
            )
        )

        self.addParameter(
            QgsProcessingParameterFeatureSink(
                'OUTPUT',
                'Tema de acometidas procesadas'
            )
        )

## BLOQUE 3: EJECUCIÓN LÓGICA DEL ALGORITMO
    def processAlgorithm(self, parameters, context, feedback):
        tramos_source = self.parameterAsSource(parameters, 'TRAMOS_RED', context)
        acometidas_source = self.parameterAsSource(parameters, 'ACOMETIDAS', context)
        campo_origen = self.parameterAsString(parameters, 'CAMPO_ID_ORIGEN', context)

        # Clonamos campos y añadimos la nueva columna requerida
        fields = acometidas_source.fields()
        fields.append(QgsField("id_pol_corte", QVariant.Int, "integer"))

        (sink, dest_id) = self.parameterAsSink(
            parameters,
            'OUTPUT',
            context,
            fields,
            acometidas_source.wkbType(),
            acometidas_source.sourceCrs()
        )

        # Tolerancia estricta de 10 centímetros para el EPSG:2530
        tolerancia = 0.10

        ## BLOQUE 4: OPTIMIZACIÓN MEDIANTE ÍNDICES ESPACIALES
        feedback.pushInfo("Generando índices espaciales en memoria...")
        
        # Inicializamos el índice espacial genérico (compatible con cualquier versión 3.x)
        index_tramos = QgsSpatialIndex()
        
        # Creamos diccionarios para almacenar geometrías y atributos en memoria RAM
        # Esto sustituye la necesidad de almacenar la geometría dentro del propio objeto del índice
        dict_geometrias_tramos = {}
        dict_valores_tramos = {}
        
        for feat in tramos_source.getFeatures():
            feat_id = feat.id()
            index_tramos.addFeature(feat)
            dict_geometrias_tramos[feat_id] = feat.geometry()
            dict_valores_tramos[feat_id] = feat[campo_origen]

        ## BLOQUE 5: ENLACE ESPACIAL Y ASIGNACIÓN DE ATRIBUTOS
        total = acometidas_source.featureCount()
        features_acometidas = acometidas_source.getFeatures()

        # Evitamos divisiones por cero si la capa está vacía
        progreso_divisor = total if total > 0 else 1

        for current, feat_acometida in enumerate(features_acometidas):
            if feedback.isCanceled():
                break

            geom_punto = feat_acometida.geometry()
            id_detectado = None

            if geom_punto and not geom_punto.isEmpty():
                # Generamos una caja de búsqueda de 10cm alrededor del punto
                bbox_busqueda = geom_punto.boundingBox()
                bbox_busqueda.grow(tolerancia)

                # Filtramos candidatos rápidos interceptando la caja de búsqueda
                candidatos = index_tramos.intersects(bbox_busqueda)

                distancia_minima = float('inf')
                
                # Análisis de distancia real sobre los candidatos pre-filtrados
                for tramo_id in candidatos:
                    geom_tramo = dict_geometrias_tramos[tramo_id]
                    distancia = geom_punto.distance(geom_tramo)

                    # Condición: debe cumplir la tolerancia y ser el objeto más cercano
                    if distancia <= tolerancia and distancia < distancia_minima:
                        distancia_minima = distancia
                        id_detectado = dict_valores_tramos[tramo_id]

            # Reconstruimos los atributos insertando el ID o NULL si no hubo coincidencia
            nuevos_atributos = feat_acometida.attributes()
            nuevos_atributos.append(id_detectado if id_detectado is not None else NULL)
            feat_acometida.setAttributes(nuevos_atributos)

            # Insertamos la entidad procesada en la capa de salida
            sink.addFeature(feat_acometida, QgsFeatureSink.FastInsert)

            feedback.setProgress(int(current * 100 / progreso_divisor))

        ## BLOQUE 6: RETORNO DE RESULTADOS
        return {'OUTPUT': dest_id}
