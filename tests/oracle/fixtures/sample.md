# Guide de déploiement applicatif

Ce guide décrit la procédure standard de mise en production des applications internes. Il s'adresse aux équipes de développement et à l'équipe d'exploitation.

## Préparation

Avant toute mise en production, l'équipe de développement vérifie que :

- la branche principale est verte en intégration continue ;
- les migrations de base de données ont été testées sur l'environnement de recette ;
- la note de version est rédigée et validée par le responsable produit.

La demande de changement est déposée dans l'outil de gestion au moins quarante-huit heures avant la fenêtre de déploiement. Elle précise le périmètre, les risques identifiés et le plan de retour arrière.

## Fenêtres de déploiement

Les déploiements ont lieu le mardi et le jeudi entre dix-huit heures et vingt heures. Aucun déploiement n'est autorisé le vendredi, la veille d'un jour férié ou pendant les périodes de clôture comptable.

| Environnement | Validation requise | Délai |
|---------------|--------------------|-------|
| Recette       | Chef de projet     | 24 h  |
| Production    | Comité de changement | 48 h |

## Exécution

1. L'exploitant annonce le début de l'intervention sur le canal dédié.
2. Il applique les migrations puis déploie la nouvelle version.
3. Il exécute les tests de fumée automatisés.
4. Il surveille les indicateurs pendant trente minutes.

En cas d'anomalie bloquante, le retour arrière est déclenché immédiatement, sans attendre la fin de la fenêtre.

## Après le déploiement

Le responsable produit confirme le bon fonctionnement auprès des utilisateurs clés. La demande de changement est clôturée avec un bilan qui mentionne la durée réelle de l'intervention et les éventuels incidents.

### Retour d'expérience

Tout incident survenu pendant un déploiement donne lieu à un retour d'expérience sous cinq jours ouvrés. Les actions correctives sont suivies dans le tableau de bord de l'équipe d'exploitation.
